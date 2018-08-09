#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Aug  8 10:33:53 2018

@author: fwilde
"""
import tango
import h5py
from datetime import datetime


class TangoMotorDb():
    """
    Create or modify a databse which holds information on OMS/ZMX driven motors
    at the P05 beamline.
    Motor information can either be retrieved by the database or from a tango
    server.
    One set of motor parameters can be cached internally, modfied and later be
    written to either the server and/or the database.

    The database is a hdf5 file which is ordered in the following way:
        motorgroup
        |___motorname
        |   |___zmx
        |   |___oms
        |   |___loc
        |___motorname ...
        motorgroup ...

    Each motor should labeled wth a unique name in a unique group.
    """

    def __init__(self, tango_host='hzgpp05vme0:10000'):
        """
        Initialize class. Defines path to database, attribute dictionary and
        tango server.

        param: tango_host <string>
            defines tango host. Port must be supplied (e.g. 'hzgpp05vme0:10000')
        """
        self.tango_host = tango_host
        self.motor_db_filepath = '/home/fwilde/desycloud/dev/python/p05tools/p05_motor_db.h5'
        self.motor_cache = {'zmx':{'AxisName':None,
                                   'PreferentialDirection':None,
                                   'RunCurrent':None,
                                   'StopCurrent':None,
                                   'StepWidth':None},
                            'oms':{'Acceleration':None,
                                   'BaseRate':None,
                                   'Conversion':None,
                                   'SettleTime':None,
                                   'SlewRate':None,
                                   'StepBacklash':None,
                                   'UnitLimitMax':None,
                                   'UnitLimitMin':None},
                            'loc':{'zmx_slot':None,
                                   'zmx_device_name':None,
                                   'oms_device_name':None}}
        self.motor_subgroups = ['zmx', 'oms', 'loc']

    def _fetch_tango_proxies(self, zmx_slot):
        """
        Creates tango device proxies based on zmx motor slot.

        param: zmx_slot <int>
            number of the zmx slot. use numbers >16 for second crate
            on hzgpp05vme0:10000 (DMM)
        """
        server_prefixes = \
            {'hzgpp05vme0:10000':{'zmx':'/p05/ZMX/mono.',
                                  'oms':'/p05/motor/mono.'},
             'hzgpp05vme1:10000':{'zmx':'/p05/ZMX/eh1.',
                                  'oms':'/p05/motor/eh1.'},
             'hzgpp05vme2:10000':{'zmx':'/p05/ZMX/eh2.',
                                  'oms':'/p05/motor/eh2.'}
            }
        # set correct server prefix for vme0 second crate
        if (self.tango_host == 'hzgpp05vme0:10000' and zmx_slot in range(17, 33)):
            server_prefixes['hzgpp05vme0:10000']['zmx'] = '/p05/ZMX/multi.'
            server_prefixes['hzgpp05vme0:10000']['oms'] = '/p05/motor/multi.'
        # Get Tango device proxy
        zmx_device_name = (self.tango_host
                           + server_prefixes[self.tango_host]['zmx']
                           + '{:02d}'.format(zmx_slot))
        zmx_device = tango.DeviceProxy(zmx_device_name)
        oms_device_name = (self.tango_host
                           + server_prefixes[self.tango_host]['oms']
                           + '{:02d}'.format(zmx_slot))
        oms_device = tango.DeviceProxy(oms_device_name)
        return {'zmx':{'device_name':zmx_device_name, 'device':zmx_device},
                'oms':{'device_name':oms_device_name, 'device':oms_device}}

    def query_server(self, zmx_slot):
        """
        Reads motor attributes fom tango server based on the ZMX slot and
        stroes the values in an internal cache.
        Motorgroup and motorname should be chosen with care since they can
        be stored in the database (e.g. 'dmm' and 'x1rot').

        param: zmx_slot <int>
            number of the zmx slot. use numbers >16 for second crate
            on hzgpp05vme0:10000 (DMM)
        param: motorgroup <str>
            Name for the group to which the motor belongs to
        param: motorname <str>
            Name of the motor
        """
        tango_proxies = self._fetch_tango_proxies(zmx_slot)
        for servertype, serverentry in tango_proxies.items():
        # fetch_zmx and oms attributes
            for attr in sorted(self.motor_cache[servertype]):
                self.motor_cache[servertype][attr] = \
                    serverentry['device'].read_attribute(attr).value
                if isinstance(self.motor_cache[servertype][attr], \
                              float):
                    self.motor_cache[servertype][attr] = \
                        round(self.motor_cache[servertype][attr], 4)
        # create 'loc' entries
        self.motor_cache['loc']['zmx_slot'] = zmx_slot
        self.motor_cache['loc']['zmx_device_name'] = tango_proxies['zmx']['device_name']
        self.motor_cache['loc']['oms_device_name'] = tango_proxies['oms']['device_name']

        self.cache_info()

    def modify_cache(self, attribute, value):
        """
        Modifies cached motor values.

        param: attribute <str>
            attribute to modify
        param: value <all>
            new value for attribute
        """
        for m_subg in self.motor_subgroups:
            for key in self.motor_cache[m_subg]:
                if key == attribute:
                    self.motor_cache[m_subg][key] = value
                    print('Inserted: {} {}'.format(attribute, value))
                    return
        print('{} not in cache (typo?)'.format(attribute))

    def write_cache_to_server(self, zmx_slot, motorgroup, motorname, update=True):
        """
        Write motor attributes from internal cache to ZMX/OMS tango servers.

        param: zmx_slot <int>
            number of the zmx slot. use numbers >16 for second crate
            on hzgpp05vme0:10000 (DMM)
        param: motorgroup <str>
            Name for the group to which the motor belongs to
        param: motorname <str>
            Name of the motor
        param: update_db <boolean> (optional)
            whether to update the database and cache automatically or not
            default: True
        """
        tango_proxies = self._fetch_tango_proxies(zmx_slot)
        for servertype, serverentry in tango_proxies.items():
        # dump zmx and oms attributes
            for attr in sorted(self.motor_cache[servertype].keys()):
                value = self.motor_cache[servertype][attr]
                serverentry['device'].write_attribute(attr, value)
            if servertype == 'zmx':
                serverentry['device'].WriteEPROM()
                print('Write ZMX attrobutes to EPROM successful.')

        if update:
            print('Updating cache and database:')
            self.motor_cache['loc']['zmx_slot'] = zmx_slot
            self.motor_cache['loc']['zmx_device_name'] = tango_proxies['zmx']['device_name']
            self.motor_cache['loc']['oms_device_name'] = tango_proxies['oms']['device_name']
            self.write_cache_to_database(motorgroup, motorname, overwrite_attrs=False)


    def cache_info(self):
        """
        Pretty prints internally cached values of a motor.
        """
        print('=' * 79)
        print('Cached attributes\n')
        for subgroup in self.motor_cache:
            for attr, value in self.motor_cache[subgroup].items():
                print('{:<9}: {:<23}: {}'.format(subgroup, attr, value))
        print('=' * 79)

    def write_cache_to_database(self, motorgroup, motorname, overwrite_attrs=False):
        """
        Write motor attributes into a h5 database on disk. Default behaviour
        for existing entries is to only overwrite 'loc' entries.
        Use 'overwrite_attrs' if other parameters should be overwritten as well.

        param: motorgroup <str>
            Name for the group to which the motor belongs to
        param: motorname <str>
            Name of the motor
        param: overwrite_attrs <boolean> (optional)
            Overwrites qlso motor attributes if true. Affects ony 'zmx' and 'oms'
            subgroups. The 'loc' entries will always be written.
        """
        p1 = motorgroup # database directory path 1st level
        p2 = p1 + '/' + motorname # database directory path 2nd level
        with h5py.File(self.motor_db_filepath, 'a') as h5db_file:
            # test if the motorgroup and motorname exist in cache
            try:
                self.motor_cache
            except KeyError:
                print('{} {} does not exist in internal \
                      dictionary.'.format(motorgroup, motorname))
                self.cache_info()
                return
            # write attributes to database, iterate over subgroups
            for m_subg in self.motor_subgroups:
                p3 = p2 + '/' + m_subg # database directory path 3rd level
                # writing in existing h5 entries will fail with a ValueError.
                # Hence for new entries:
                try:
                    zmx_group = h5db_file.create_group(p3)
                    for attr, value in self.motor_cache[m_subg].items():
                        zmx_group.create_dataset(attr, data=value)

                    for path in [p1, p2, p3]: # update timestamps in database
                        h5db_file[path].attrs.create('last edit', str(datetime.now()), dtype="S19")

                # or, if the entry exists:
                except ValueError:
                    if overwrite_attrs:
                        print('Group already exists, Overwriting: {}'.format(p3))
                        for attr, value in self.motor_cache[m_subg].items():
                            del h5db_file[p3 + '/'+attr]
                            h5db_file[p3].create_dataset(attr, data=value)
                        for path in [p1, p2, p3]: # update timestamps in database
                            h5db_file[path].attrs.create('last edit', str(datetime.now()), dtype="S19")
                    else:
                        if m_subg != 'loc':
                            print('Group already exists. No ovwrite_attrs flag  set. Skipping  {}.'.format(m_subg))
                            continue
                        else:
                            print('Group already exists, Overwriting: {}'.format(p3))
                            for attr, value in self.motor_cache['loc'].items():
                                del h5db_file[p2 + '/loc/'+attr]
                                h5db_file[p2 + '/loc'].create_dataset(attr, data=value)
                            for path in [p1, p2, p3]: # update timestamps in database
                                h5db_file[path].attrs.create('last edit', str(datetime.now()), dtype="S19")
            h5db_file.close()


    def query_database(self, motorgroup, motorname):
        """
        Reads a single motor entry from the database into the internally stored
        cache.

        param: motorgroup <str>
            Name for the group to which the motor belongs to
        param: motorname <str>
            Name of the motor
        """
        with h5py.File(self.motor_db_filepath, 'r') as h5db_file:
            # create empty motor group entries if necessary
            for m_subg in self.motor_subgroups:
                for attr in self.motor_cache[m_subg].keys():
                    self.motor_cache[m_subg][attr] = \
                        h5db_file[motorgroup + '/' + motorname + '/'+ m_subg + '/'+attr].value
            h5db_file.close()
        self.database_info(motorgroup, motorname)

    def _retrieve_database_entries(self):
        """
        Fetches a list of all entries in database.
        """
        with h5py.File(self.motor_db_filepath, 'r') as h5db_file:
            db_entries = []
            for motorgroup in h5db_file.keys():
                for motorname in h5db_file[motorgroup].keys():
                    db_entries.append([motorgroup, motorname])
            h5db_file.close()
        return db_entries

    def database_info(self, motorgroup=None, motorname=None):
        """
        Shows information about h5 database stored motors. If any parameter
        is omitted, an overview of the database contents will be printed instead.

        param: motorgroup <str> (optional)
            Name for the group to which the motor belongs to
            default: None
        param: motorname <str> (optional)
            Name of the motor
            defaul: None
        """
        db_entries = self._retrieve_database_entries()
        if not (motorgroup and motorname):
            print('=' * 79)
            print('The database currently contains attributes for these motors:\n')
            for item in db_entries:
                print('{:<10} {}'.format(item[0], item[1]))
            print('=' * 79)
            return
        print('=' * 79)
        print('{} {} attributes\n'.format(motorgroup, motorname))

        with h5py.File(self.motor_db_filepath, 'r') as h5db_file:
            # create empty motor group entries if necessary
            for m_subg in self.motor_subgroups:
                for attr in self.motor_cache[m_subg].keys():
                    value = h5db_file[motorgroup + '/' + motorname + '/'+ m_subg + '/'+attr].value
                    print('{:<9}: {:<23}: {}'.format(m_subg, attr, value))
            h5db_file.close()
        print('=' * 79)


if __name__ == '__main__':
    TM = TangoMotorDb()
