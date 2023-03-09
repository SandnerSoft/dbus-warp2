#!/usr/bin/env python

import platform 
import logging
import logging.handlers
import sys
import os
import sys
if sys.version_info.major == 2:
    import gobject
else:
    from gi.repository import GLib as gobject
import sys
import time
import requests 
import configparser

# für Websocket
import websocket
import _thread
import rel

# our own packages from victron
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '/opt/victronenergy/dbus-systemcalc-py/ext/velib_python'))
from vedbus import VeDbusService

class DbusWarp2Service:
    def _on_message(ws, message):
        print(message)

    def _on_error(ws, error):
        print(error)

    def _on_close(ws, close_status_code, close_msg):
        print("### closed ###")

    def _on_open(ws):
        print("Opened connection")

    def _getConfig(self):
        config = configparser.ConfigParser()
        config.read("%s/config.ini" % (os.path.dirname(os.path.realpath(__file__))))
        return config;

    def __init__(self, servicename, paths, productname='WARP2 Smart', connection='WARP2 Smart HTTP service'):
        config = self._getConfig()
        deviceinstance = int(config['DEFAULT']['Deviceinstance'])
        
        self._dbusservice = VeDbusService("{}.http_{:02d}".format(servicename, deviceinstance))
        self._paths = paths
        
        logging.debug("%s /DeviceInstance = %d" % (servicename, deviceinstance))
        
        paths_wo_unit = [
        '/Status',  # value 'car' 1: charging station ready, no vehicle 2: vehicle loads 3: Waiting for vehicle 4: Charge finished, vehicle still connected
        '/Mode'
        ]
    
        #get data from go-eCharger
        #data = self._getGoeChargerData()
        websocket.enableTrace(True)
        ws = websocket.WebSocketApp("ws://" + config['ONPREMISE']['Host'] + "/ws",
                                on_open = _on_open,
                                on_message = _on_message,
                                on_error = _on_error,
                                on_close = _on_close)

        ws.run_forever(dispatcher=rel, reconnect=5)
        rel.signal(2, rel.abort)  # Keyboard Interrupt
        rel.dispatch()

        # Create the management objects, as specified in the ccgx dbus-api document
        self._dbusservice.add_path('/Mgmt/ProcessName', __file__)
        self._dbusservice.add_path('/Mgmt/ProcessVersion', 'Unkown version, and running on Python ' + platform.python_version())
        self._dbusservice.add_path('/Mgmt/Connection', connection)
        
        # Create the mandatory objects
        self._dbusservice.add_path('/DeviceInstance', deviceinstance)
        self._dbusservice.add_path('/ProductId', 0xFFFF) # 
        self._dbusservice.add_path('/ProductName', productname)
        self._dbusservice.add_path('/CustomName', productname)    
        self._dbusservice.add_path('/FirmwareVersion', int(data['fwv'].replace('.', '')))
        self._dbusservice.add_path('/HardwareVersion', 2)
        self._dbusservice.add_path('/Serial', data['sse'])
        self._dbusservice.add_path('/Connected', 1)
        self._dbusservice.add_path('/UpdateIndex', 0)
        
        # add paths without units
        for path in paths_wo_unit:
            self._dbusservice.add_path(path, None)
        
        # add path values to dbus
        for path, settings in self._paths.items():
            self._dbusservice.add_path(
                path, settings['initial'], gettextcallback=settings['textformat'], writeable=True, onchangecallback=self._handlechangedvalue)

        # last update
        self._lastUpdate = 0
        
        # charging time in float
        self._chargingTime = 0.0

        # add _update function 'timer'
        #gobject.timeout_add(250, self._update) # pause 250ms before the next request
        
        # add _signOfLife 'timer' to get feedback in log every 5minutes
        gobject.timeout_add(self._getSignOfLifeInterval()*60*1000, self._signOfLife)


def getLogLevel():
    config = configparser.ConfigParser()
    config.read("%s/config.ini" % (os.path.dirname(os.path.realpath(__file__))))
    logLevelString = config['DEFAULT']['LogLevel']
    
    if logLevelString:
        level = logging.getLevelName(logLevelString)
    else:
        level = logging.INFO
        
    return level

def main():
    logging.basicConfig(format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                            datefmt='%Y-%m-%d %H:%M:%S',
                            level=getLogLevel(),
                            handlers=[
                                logging.FileHandler("%s/current.log" % (os.path.dirname(os.path.realpath(__file__)))),
                                logging.StreamHandler()])
    
    try:
        logging.info("Start");
    
        from dbus.mainloop.glib import DBusGMainLoop
        # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
        DBusGMainLoop(set_as_default=True)

        #formatting 
        _kwh = lambda p, v: (str(round(v, 2)) + 'kWh')
        _a = lambda p, v: (str(round(v, 1)) + 'A')
        _w = lambda p, v: (str(round(v, 1)) + 'W')
        _v = lambda p, v: (str(round(v, 1)) + 'V')
        _degC = lambda p, v: (str(v) + '°C')
        _s = lambda p, v: (str(v) + 's')
        
        #start our main-service
        pvac_output = DbusWarp2Service(
            servicename='com.victronenergy.evcharger',
            paths={
                '/Ac/Power': {'initial': 0, 'textformat': _w},
                '/Ac/L1/Power': {'initial': 0, 'textformat': _w},
                '/Ac/L2/Power': {'initial': 0, 'textformat': _w},
                '/Ac/L3/Power': {'initial': 0, 'textformat': _w},
                '/Ac/Energy/Forward': {'initial': 0, 'textformat': _kwh},
                '/ChargingTime': {'initial': 0, 'textformat': _s},
                
                '/Ac/Voltage': {'initial': 0, 'textformat': _v},
                '/Current': {'initial': 0, 'textformat': _a},
                '/SetCurrent': {'initial': 0, 'textformat': _a},
                '/MaxCurrent': {'initial': 0, 'textformat': _a},
                '/MCU/Temperature': {'initial': 0, 'textformat': _degC},
                '/StartStop': {'initial': 0, 'textformat': lambda p, v: (str(v))}
                }
            )
        
        logging.info('Connected to dbus, and switching over to gobject.MainLoop() (= event based)')
        mainloop = gobject.MainLoop()
        mainloop.run()
    except Exception as e:
        logging.critical('Error at %s', 'main', exc_info=e)

if __name__ == "__main__":
    main()