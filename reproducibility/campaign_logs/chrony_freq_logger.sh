#!/usr/bin/env bash
# chrony_freq_logger.sh -- one line per minute of the driver clock discipline state, soevery cell in
# chains 17+ can be joined to the clock behaviour during its run. Residual freq is the effective
# clock-rate error (ppm) after chrony correction; System-time offset shows slew events.
while true; do
  echo "$(date -u +%FT%TZ) $(chronyc tracking | grep -E 'System time|Residual freq|Skew' | tr -s ' ' | tr '
' '|')" >> ~/sbl/docs/results/external/chrony_freq.log
  sleep 60
done
