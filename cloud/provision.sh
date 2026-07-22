#!/usr/bin/env bash
# Provision the multi-host testbed on Oracle Cloud via the OCI CLI.
#
# Prerequisites (done once, by a human - this script never handles credentials):
#   pip install oci-cli
#   oci setup bootstrap --profile-name DEFAULT --region <your-home-region>
#
# Capacity notes, from actually doing this in uk-london-1:
#   * VM.Standard.A1.Flex (the Always Free ARM shape) and VM.Standard.E4.Flex were BOTH
#     "Out of host capacity" in every availability domain. Quota is not capacity: A1 showed
#     41 cores of quota and still refused to launch.
#   * VM.Standard.E5.Flex, E3.Flex and Standard3.Flex had capacity. E5 is used below.
#   * E5 is a PAID shape. On a 30-day trial it draws down the credit (~$0.31/hr for this set);
#     on a paid tenancy it bills. Always Free is E2.1.Micro only, and only in some ADs.
set -euo pipefail

OCI="${OCI:-oci}"
AD="${AD:-1}"                       # availability domain index
SHAPE="${SHAPE:-VM.Standard.E5.Flex}"
IMAGE_OS="${IMAGE_OS:-Canonical Ubuntu}"
IMAGE_VER="${IMAGE_VER:-22.04}"
SSH_PUB="${SSH_PUB:-$HOME/.ssh/oci_sbl.pub}"
CIDR_VCN="${CIDR_VCN:-10.0.0.0/16}"
CIDR_SUB="${CIDR_SUB:-10.0.1.0/24}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

T=$("$OCI" iam availability-domain list --query 'data[0]."compartment-id"' --raw-output)
ADNAME=$("$OCI" iam availability-domain list --query "data[$((AD-1))].name" --raw-output)
echo "tenancy ok; using $ADNAME shape $SHAPE"

VCN=$("$OCI" network vcn create --compartment-id "$T" --display-name sbl-vcn \
  --cidr-blocks "[\"$CIDR_VCN\"]" --dns-label sblvcn --wait-for-state AVAILABLE \
  --query 'data.id' --raw-output)
IGW=$("$OCI" network internet-gateway create --compartment-id "$T" --vcn-id "$VCN" \
  --is-enabled true --display-name sbl-igw --wait-for-state AVAILABLE \
  --query 'data.id' --raw-output)
RT=$("$OCI" network vcn get --vcn-id "$VCN" --query 'data."default-route-table-id"' --raw-output)
"$OCI" network route-table update --rt-id "$RT" --force \
  --route-rules "[{\"destination\":\"0.0.0.0/0\",\"destinationType\":\"CIDR_BLOCK\",\"networkEntityId\":\"$IGW\"}]" >/dev/null

# Broker ports are reachable ONLY from inside the VCN. An unauthenticated Redis on a public
# IP is compromised within minutes (CONFIG SET dir + SAVE writes an SSH key), so it is never
# exposed here. SSH is key-only.
SL=$("$OCI" network vcn get --vcn-id "$VCN" --query 'data."default-security-list-id"' --raw-output)
cat > /tmp/sbl_ingress.json <<JSON
[ {"protocol":"6","source":"0.0.0.0/0","isStateless":false,
   "tcpOptions":{"destinationPortRange":{"min":22,"max":22}},"description":"SSH (key-only)"},
  {"protocol":"all","source":"$CIDR_VCN","isStateless":false,
   "description":"intra-VCN broker traffic stays private"},
  {"protocol":"1","source":"0.0.0.0/0","isStateless":false,
   "icmpOptions":{"type":3,"code":4},"description":"path MTU discovery"} ]
JSON
"$OCI" network security-list update --security-list-id "$SL" --force \
  --ingress-security-rules file:///tmp/sbl_ingress.json >/dev/null

SUB=$("$OCI" network subnet create --compartment-id "$T" --vcn-id "$VCN" \
  --display-name sbl-subnet --cidr-block "$CIDR_SUB" --dns-label sblsub \
  --wait-for-state AVAILABLE --query 'data.id' --raw-output)

IMG=$("$OCI" compute image list --compartment-id "$T" --operating-system "$IMAGE_OS" \
  --operating-system-version "$IMAGE_VER" --shape "$SHAPE" \
  --query 'data[0].id' --raw-output)

launch () {  # name ocpus mem_gb
  "$OCI" compute instance launch --compartment-id "$T" --availability-domain "$ADNAME" \
    --display-name "$1" --shape "$SHAPE" \
    --shape-config "{\"ocpus\":$2,\"memoryInGBs\":$3}" \
    --image-id "$IMG" --subnet-id "$SUB" --assign-public-ip true \
    --ssh-authorized-keys-file "$SSH_PUB" --user-data-file "$HERE/cloud-init.yaml" \
    --query 'data.id' --raw-output
}

launch sbl-b1  1 8  > /tmp/sbl-b1.id
launch sbl-b2  1 8  > /tmp/sbl-b2.id
launch sbl-b3  1 8  > /tmp/sbl-b3.id
launch sbl-drv 4 24 > /tmp/sbl-drv.id

echo "launched. Collect IPs with:"
echo "  oci compute instance list-vnics --instance-id \$(cat /tmp/sbl-b1.id)"
echo "then write cloud/hosts.env (see hosts.env.example) and run cloud/brokers.sh on each broker."
