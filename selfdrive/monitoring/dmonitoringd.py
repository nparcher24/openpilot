#!/usr/bin/env python3
import cereal.messaging as messaging
from cereal import log
from openpilot.common.realtime import config_realtime_process, Ratekeeper

# ndm: DRIVER MONITORING DISABLED FOR RESOURCE TESTING.
# The DM neural net (dmonitoringmodeld) and the driver camera (DISABLE_DRIVER in
# launch_env.sh) are turned off to measure their resource usage. selfdrived and
# controlsd require `driverMonitoringState` to be alive, so this stub publishes a
# constant "attentive" state at the normal 20Hz. The system therefore engages
# normally with zero DM alerts and zero actual monitoring capability.
# Revert this commit (see git history for the original policy-driven loop) to
# restore real driver monitoring.

DM_RATE_HZ = 20  # cereal/services.py: driverMonitoringState @ 20Hz


def dmonitoringd_thread():
  config_realtime_process([0, 1, 2, 3], 5)

  pm = messaging.PubMaster(['driverMonitoringState'])
  rk = Ratekeeper(DM_RATE_HZ, print_delay_threshold=None)

  while True:
    dat = messaging.new_message('driverMonitoringState', valid=True)
    dm = dat.driverMonitoringState
    # everything selfdrived/controlsd inspect, pinned to "attentive / no lockout"
    dm.alertLevel = log.DriverMonitoringState.AlertLevel.none
    dm.activePolicy = log.DriverMonitoringState.MonitoringPolicy.vision
    dm.lockout = False
    dm.alwaysOn = False
    dm.alwaysOnLockout = False
    dm.isRHD = False
    dm.visionPolicyState.faceDetected = True
    dm.visionPolicyState.isDistracted = False
    dm.visionPolicyState.awarenessPercent = 100
    dm.visionPolicyState.uncertainOffroadAlertPercent = 0
    pm.send('driverMonitoringState', dat)

    rk.keep_time()


def main():
  dmonitoringd_thread()


if __name__ == '__main__':
  main()
