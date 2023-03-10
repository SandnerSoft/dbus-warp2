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

import websocket
import _thread
import time
import rel

# our own packages from victron
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '/opt/victronenergy/dbus-systemcalc-py/ext/velib_python'))
from vedbus import VeDbusService

class DbusWarp2Service:
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
        firmware = self._getFirmwareVersion()
        warp_name = self._getWarp2Name()
        position = config['DEFAULT']['Position']

        # Create the management objects, as specified in the ccgx dbus-api document
        self._dbusservice.add_path('/Mgmt/ProcessName', __file__)
        self._dbusservice.add_path('/Mgmt/ProcessVersion', 'Python ' + platform.python_version())
        self._dbusservice.add_path('/Mgmt/Connection', connection)
        
        # Create the mandatory objects
        self._dbusservice.add_path('/DeviceInstance', deviceinstance)
        self._dbusservice.add_path('/ProductId', 0xFFFF) # 
        self._dbusservice.add_path('/ProductName', productname)
        self._dbusservice.add_path('/CustomName', productname)    
        self._dbusservice.add_path('/FirmwareVersion', firmware['firmware'])
        self._dbusservice.add_path('/HardwareVersion', firmware['config'])
        self._dbusservice.add_path('/Serial', warp_name['name'])
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
        gobject.timeout_add(2000, self._update) # pause 250ms before the next request
        
        # add _signOfLife 'timer' to get feedback in log every 5minutes
        gobject.timeout_add(self._getSignOfLifeInterval()*60*1000, self._signOfLife)

    def _update(self):
        try:
            state = self._getWarp2State()
            hardware = self._getWarp2Hardware()

            self._dbusservice['/Ac/Voltage'] = 0
            self._dbusservice['/Mode'] = 0  # Manual, no control
            
            self._setPosition()

            # value 'car' 1: charging station ready, no vehicle 2: vehicle loads 3: Waiting for vehicle 4: Charge finished, vehicle still connected
            status = 0
            if int(state['charger_state']) == 0:
                status = 0
            elif int(state['charger_state']) == 1:
                status = 4
            elif int(state['charger_state']) == 2:
                status = 6
            elif int(state['charger_state']) == 3:
                status = 2
            elif int(state['charger_state']) == 4:
                status = 7
            self._dbusservice['/Status'] = status

            max_current = 0
            if int(hardware['jumper_configuration']) == 0:
                max_current = 6
            elif int(hardware['jumper_configuration']) == 1:
                max_current = 10
            elif int(hardware['jumper_configuration']) == 2:
                max_current = 13
            elif int(hardware['jumper_configuration']) == 3:
                max_current = 16
            elif int(hardware['jumper_configuration']) == 4:
                max_current = 20
            elif int(hardware['jumper_configuration']) == 5:
                max_current = 25
            elif int(hardware['jumper_configuration']) == 6:
                max_current = 32
            else:
                max_current = 0
            self._dbusservice['/MaxCurrent'] = max_current


            # increment UpdateIndex - to show that new data is available
            index = self._dbusservice['/UpdateIndex'] + 1  # increment index
            if index > 255:   # maximum value of the index
                index = 0       # overflow from 255 to 0
            self._dbusservice['/UpdateIndex'] = index

            #update lastupdate vars
            self._lastUpdate = time.time()    

        except Exception as e:
            logging.critical('Error at %s', '_update', exc_info=e)

    def _setPosition(self):
        config = self._getConfig()
        position = int(config['DEFAULT']['Position'])

        if position == 0:
            self._dbusservice['/Position'] = 0
        elif position == 1:
            self._dbusservice['/Position'] = 1
        else:
            raise ValueError("Position %s is not supported" % (config['DEFAULT']['Position']))
        
        return true

    def _getWarp2Hardware(self):
        config = self._getConfig()
        accessType = config['DEFAULT']['AccessType']
        
        if accessType == 'OnPremise': 
            URL = "http://%s/evse/hardware_configuration" % (config['ONPREMISE']['Host'])
        else:
            raise ValueError("AccessType %s is not supported" % (config['DEFAULT']['AccessType']))

        request_data = requests.get(url = URL)
    
        # check for response
        if not request_data:
            raise ConnectionError("No response from WARP2 - %s" % (URL))
        
        json_data = request_data.json()     
        
        # check for Json
        if not json_data:
            raise ValueError("Converting response to JSON failed")
        
        return json_data

    def _getWarp2Name(self):
        config = self._getConfig()
        accessType = config['DEFAULT']['AccessType']
        
        if accessType == 'OnPremise': 
            URL = "http://%s/info/name" % (config['ONPREMISE']['Host'])
        else:
            raise ValueError("AccessType %s is not supported" % (config['DEFAULT']['AccessType']))

        request_data = requests.get(url = URL)
    
        # check for response
        if not request_data:
            raise ConnectionError("No response from WARP2 - %s" % (URL))
        
        json_data = request_data.json()     
        
        # check for Json
        if not json_data:
            raise ValueError("Converting response to JSON failed")
        
        return json_data

    def _getFirmwareVersion(self):
        config = self._getConfig()
        accessType = config['DEFAULT']['AccessType']
        
        if accessType == 'OnPremise': 
            URL = "http://%s/info/version" % (config['ONPREMISE']['Host'])
        else:
            raise ValueError("AccessType %s is not supported" % (config['DEFAULT']['AccessType']))

        request_data = requests.get(url = URL)
    
        # check for response
        if not request_data:
            raise ConnectionError("No response from WARP2 - %s" % (URL))
        
        json_data = request_data.json()     
        
        # check for Json
        if not json_data:
            raise ValueError("Converting response to JSON failed")
        
        return json_data

    def _getWarp2State(self):
        config = self._getConfig()
        accessType = config['DEFAULT']['AccessType']
        
        if accessType == 'OnPremise': 
            URL = "http://%s/evse/state" % (config['ONPREMISE']['Host'])
        else:
            raise ValueError("AccessType %s is not supported" % (config['DEFAULT']['AccessType']))

        request_data = requests.get(url = URL)
    
        # check for response
        if not request_data:
            raise ConnectionError("No response from WARP2 - %s" % (URL))
        
        json_data = request_data.json()     
        
        # check for Json
        if not json_data:
            raise ValueError("Converting response to JSON failed")
        
        return json_data

    def _getConfig(self):
        config = configparser.ConfigParser()
        config.read("%s/config.ini" % (os.path.dirname(os.path.realpath(__file__))))
        return config

    def _handlechangedvalue(self, path, value):
        logging.debug("someone else updated %s to %s" % (path, value))
        return True # accept the change
    
    def _getSignOfLifeInterval(self):
        config = self._getConfig()
        value = config['DEFAULT']['SignOfLifeLog']
        
        if not value: 
            value = 0
        
        return int(value)

    def _signOfLife(self):
        logging.info("--- Start: sign of life ---")
        logging.info("Last _update() call: %s" % (self._lastUpdate))
        logging.info("Last Updateinterval: %s" % (self._dbusservice['/UpdateIndex']))
        logging.info("--- End: sign of life ---")
        return True

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
                '/StartStop': {'initial': 0, 'textformat': lambda p, v: (str(v))},

                '/Position': {'initial': 0, 'textformat': _s}
                }
            )
        
        logging.info('Connected to dbus, and switching over to gobject.MainLoop() (= event based)')
        mainloop = gobject.MainLoop()
        mainloop.run()
    except Exception as e:
        logging.critical('Error at %s', 'main', exc_info=e)

if __name__ == "__main__":
    main()