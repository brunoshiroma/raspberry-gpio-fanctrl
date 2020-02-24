#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys, os, time, atexit
import signal
import RPi.GPIO as GPIO
import logging as Logging
from logging.handlers import RotatingFileHandler

#logging.basicConfig(filename="/var/log/fan_ctrl.log", level=logging.DEBUG, maxBytes=1024, format='%(asctime)s %(message)s')
logging = Logging.getLogger('fanctrl')
handler = RotatingFileHandler("/var/log/fan_ctrl.log", maxBytes=2048, backupCount=0)
handler.setFormatter(Logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logging.addHandler(handler)
logging.setLevel(Logging.INFO)

class Daemon:
    """
    A generic daemon class.

    Usage: subclass the Daemon class and override the run() method
    """
    def __init__(self, pidfile, stdin='/dev/null', stdout='/dev/null', stderr='/dev/null'):
            self.stdin = stdin
            self.stdout = stdout
            self.stderr = stderr
            self.pidfile = pidfile

    def daemonize(self):
            """
            do the UNIX double-fork magic, see Stevens' "Advanced
            Programming in the UNIX Environment" for details (ISBN 0201563177)
            http://www.erlenstar.demon.co.uk/unix/faq_2.html#SEC16
            """
            try:
                    pid = os.fork()
                    if pid > 0:
                            # exit first parent
                            sys.exit(0)
            except OSError, e:
                    logging.warn("fork #1 failed: %d (%s)\n" % (e.errno, e.strerror))
                    sys.stderr.write("fork #1 failed: %d (%s)\n" % (e.errno, e.strerror))
                    sys.exit(1)

            # decouple from parent environment
            os.chdir("/")
            os.setsid()
            os.umask(0)

            # do second fork
            try:
                    pid = os.fork()
                    if pid > 0:
                            # exit from second parent
                            sys.exit(0)
            except OSError, e:
                    logging.warn("fork #2 failed: %d (%s)\n" % (e.errno, e.strerror))
                    sys.stderr.write("fork #2 failed: %d (%s)\n" % (e.errno, e.strerror))
                    sys.exit(1)

            # redirect standard file descriptors
            sys.stdout.flush()
            sys.stderr.flush()
            si = file(self.stdin, 'r')
            so = file(self.stdout, 'a+')
            se = file(self.stderr, 'a+', 0)
            os.dup2(si.fileno(), sys.stdin.fileno())
            os.dup2(so.fileno(), sys.stdout.fileno())
            os.dup2(se.fileno(), sys.stderr.fileno())

            # write pidfile
            atexit.register(self.delpid)
            pid = str(os.getpid())
            file(self.pidfile,'w+').write("%s\n" % pid)

    def delpid(self):
            os.remove(self.pidfile)

    def start(self):
            """
            Start the daemon
            """
            # Check for a pidfile to see if the daemon already runs
            try:
                    pf = file(self.pidfile,'r')
                    pid = int(pf.read().strip())
                    pf.close()
            except IOError:
                    pid = None

            if pid:
                    message = "pidfile %s already exist. Daemon already running?\n"
                    logging.warn("pidfile %s already exist. Daemon already running?\n")
                    sys.stderr.write(message % self.pidfile)
                    sys.exit(1)

            # Start the daemon
            self.daemonize()
            self.run()

    def stop(self):

            """
            Stop the daemon
            """
            # Get the pid from the pidfile
            try:
                    pf = file(self.pidfile,'r')
                    pid = int(pf.read().strip())
                    pf.close()
            except IOError:
                    pid = None

            if not pid:
                    message = "pidfile %s does not exist. Daemon not running?\n"
                    sys.stderr.write(message % self.pidfile)
                    return # not an error in a restart

            # Try killing the daemon process
            try:
                    while 1:
                            os.kill(pid, signal.SIGTERM)
                            time.sleep(0.1)
            except OSError, err:
                    err = str(err)
                    if err.find("No such process") > 0:
                            if os.path.exists(self.pidfile):
                                    os.remove(self.pidfile)
                    else:
                            print str(err)
                            sys.exit(1)

    def restart(self):
            """
            Restart the daemon
            """
            self.stop()
            self.start()

    def run(self):
        pass



class MyDaemon(Daemon):
    def run(self):
        # Configuration
        FAN_PIN = 12  # BCM pin used to drive transistor's base
        WAIT_TIME = 1  # [s] Time to wait between each refresh
        FAN_MIN = 20  # [%] Fan minimum speed.
        PWM_FREQ = 25  # [Hz] Change this value if fan has strange behavior

        # Configurable temperature and fan speed steps
        tempSteps = [40, 50, 60, 70]  # [°C]
        speedSteps = [0, 70, 90, 100]  # [%]

        # Fan speed will change only of the difference of temperature is higher than hysteresis
        hyst = 1

        # Setup GPIO pin
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(FAN_PIN, GPIO.OUT, initial=GPIO.LOW)
        fan = GPIO.PWM(FAN_PIN, PWM_FREQ)
        fan.start(0)

        i = 0
        cpuTemp = 0
        fanSpeed = 0
        cpuTempOld = 0
        fanSpeedOld = 0

        # We must set a speed value for each temperature step
        if len(speedSteps) != len(tempSteps):
            print("Numbers of temp steps and speed steps are different")
            exit(0)

        while 1:
            # Read CPU temperature
            cpuTempFile = open("/sys/class/thermal/thermal_zone0/temp", "r")
            cpuTemp = float(cpuTempFile.read()) / 1000
            cpuTempFile.close()
            logging.debug(cpuTemp)

            # Calculate desired fan speed
            if abs(cpuTemp - cpuTempOld) > hyst:
                # Below first value, fan will run at min speed.
                if cpuTemp < tempSteps[0]:
                    fanSpeed = speedSteps[0]
                # Above last value, fan will run at max speed
                elif cpuTemp >= tempSteps[len(tempSteps) - 1]:
                    fanSpeed = speedSteps[len(tempSteps) - 1]
                # If temperature is between 2 steps, fan speed is calculated by linear interpolation
                else:
                    for i in range(0, len(tempSteps) - 1):
                        if (cpuTemp >= tempSteps[i]) and (cpuTemp < tempSteps[i + 1]):
                            fanSpeed = round((speedSteps[i + 1] - speedSteps[i])
                                             / (tempSteps[i + 1] - tempSteps[i])
                                             * (cpuTemp - tempSteps[i])
                                             + speedSteps[i], 1)

                if fanSpeed != fanSpeedOld:
                    if (fanSpeed != fanSpeedOld and (fanSpeed >= FAN_MIN or fanSpeed == 0)):
                        fan.ChangeDutyCycle(fanSpeed)
                        fanSpeedOld = fanSpeed
                cpuTempOld = cpuTemp

            # Wait until next refresh
            time.sleep(WAIT_TIME)

if __name__ == "__main__":
    daemon = MyDaemon('/run/fanctrl.pid')
    if len(sys.argv) == 2:
        if 'start' == sys.argv[1]:
            daemon.start()
        elif 'stop' == sys.argv[1]:
            daemon.stop()
        elif 'restart' == sys.argv[1]:
            daemon.restart()
        else:
            print "Unknown command"
            sys.exit(2)
        sys.exit(0)
    else:
        print "usage: %s start|stop|restart" % sys.argv[0]
        sys.exit(2)

def stopGPIO():
    GPIO.clean()

signal.signal(signal.SIGINT, stopGPIO)
signal.signal(signal.SIGTERM, stopGPIO)
