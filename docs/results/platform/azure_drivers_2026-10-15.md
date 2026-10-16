# Client software on the Azure drivers, as read on 15 October 2026

Supplement Table S2 gives the client versions the Azure runs used. No run folder records them,
so they were read on the drivers themselves, over SSH, on 15 October 2026, and are kept here
verbatim. The versions are those installed on that day; the image pins `kafka-python>=2.3,<3`
and `redis>=7,<8` (`cloud/azure/cloud-init.yaml`), so an earlier run can only have used a
version inside those ranges.

## First x86 pair's driver (`cloud/hosts.env`), 14:56 UTC

Command:

```
python3 -c "import kafka, redis, sys; print('kafka-python', kafka.__version__); print('redis-py', redis.__version__); print(sys.version.split()[0])"; java -version 2>&1 | head -1; ls ~/sbl/harness/java/lib
```

Output:

```
kafka-python 2.3.2
redis-py 7.4.1
3.10.12
openjdk version "11.0.32.1" 2026-08-18
kafka-clients.jar
slf4j-api.jar
```

## Second x86 pair's driver (`cloud/hosts_b.env`), 18:53 UTC

Command:

```
java -version 2>&1 | head -3; ls /usr/lib/jvm/; dpkg -l | grep -i openjdk | awk '{print $2, $3}' | head -5
```

Output:

```
openjdk version "11.0.32.1" 2026-08-18
OpenJDK Runtime Environment (build 11.0.32.1+1-post-1ubuntu1-22.04-Ubuntu)
OpenJDK 64-Bit Server VM (build 11.0.32.1+1-post-1ubuntu1-22.04-Ubuntu, mixed mode, sharing)
java-1.11.0-openjdk-amd64
java-1.17.0-openjdk-amd64
java-1.8.0-openjdk-amd64
java-11-openjdk-amd64
java-17-openjdk-amd64
java-8-openjdk-amd64
openjdk-11-jdk-headless:amd64 11.0.32.1+1-1ubuntu1~22.04
openjdk-11-jre-headless:amd64 11.0.32.1+1-1ubuntu1~22.04
openjdk-17-jdk-headless:amd64 17.0.20.1+1-1~22.04
openjdk-17-jre-headless:amd64 17.0.20.1+1-1~22.04
openjdk-8-jdk-headless:amd64 8u504-ga-1ubuntu1~22.04.3
```

The default `java` is OpenJDK 11 on both drivers. OpenJDK 17 and 8 are also installed, by the
tools blocks (`cloud/azure/tools.sh` builds some tools with `JAVA_HOME` set to 17 or 11); the
Java client harness (`harness/java`) runs the default `java`.
