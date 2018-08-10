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
            defines tango host. Port must be supplied
            (e.g. 'hzgpp05vme0:10000')
        """
        self._tango_host = tango_host
        self._motor_db_filepath = '/home/fwilde/desycloud/dev/python/p05tools/p05_motor_db.h5'
        self._motor_cache = {'zmx': {'AxisName': None,
                                     'PreferentialDirection': None,
                                     'RunCurrent': None,
                                     'StopCurrent': None,
                                     'StepWidth': None},
                             'oms': {'Acceleration': None,
                                     'BaseRate': None,
                                     'Conversion': None,
                                     'SettleTime': None,
                                     'SlewRate': None,
                                     'StepBacklash': None,
                                     'UnitLimitMax': None,
                                     'UnitLimitMin': None},
                             'loc': {'zmx_slot': None,
                                     'zmx_device_name': None,
                                     'oms_device_name': None}}
        self._database_entry = {'motorgroup': None, 'motorname': None}
        self._motor_subgroups = ['zmx', 'oms', 'loc']
        self._server_prefixes = \
            {'hzgpp05vme0:10000':{'zmx': '/p05/ZMX/mono.',
                                  'oms': '/p05/motor/mono.'},
             'hzgpp05vme1:10000':{'zmx': '/p05/ZMX/eh1.',
                                  'oms': '/p05/motor/eh1.'},
             'hzgpp05vme2:10000':{'zmx': '/p05/ZMX/eh2.',
                                  'oms': '/p05/motor/eh2.'}
            }

    def _fetch_tango_proxies(self, zmx_slot):
        """
        Creates tango device proxies based on zmx motor slot.

        param: zmx_slot <int>
            number of the zmx slot. use numbers >16 for second crate
            on hzgpp05vme0:10000 (DMM)
        """

        # set correct server prefix for vme0 second crate
        if (self._tango_host == 'hzgpp05vme0:10000' and zmx_slot in range(17, 33)):
            self._server_prefixes['hzgpp05vme0:10000']['zmx'] = '/p05/ZMX/multi.'
            self._server_prefixes['hzgpp05vme0:10000']['oms'] = '/p05/motor/multi.'
        # Get Tango device proxy
        zmx_device_name = (self._tango_host
                           + self._server_prefixes[self._tango_host]['zmx']
                           + '{:02d}'.format(zmx_slot))
        zmx_device = tango.DeviceProxy(zmx_device_name)
        oms_device_name = (self._tango_host
                           + self._server_prefixes[self._tango_host]['oms']
                           + '{:02d}'.format(zmx_slot))
        oms_device = tango.DeviceProxy(oms_device_name)
        return {'zmx':{'device_name': zmx_device_name, 'device': zmx_device},
                'oms':{'device_name': oms_device_name, 'device': oms_device}}

    def switch_tango_host(self, tango_host=None, verbose=True):
        """
        Sets new tango host. Checks if the tango host is know to the class.

        param: tango_host <str> (optional)
            Name of the new tango host. Port must be included,
            e.g. 'hzgpp05vme0:10000'. If tango_host is omitted, a list of
            known tango hosts will be shown.
        param: verbose <boolean>
            Print information to console.
            default: True
        """
        if tango_host:
            if tango_host in self._server_prefixes.keys():
                self._tango_host = tango_host
                if verbose:
                    print('Changed tango host to: {}'.format(tango_host))
            else:
                raise Exception('Error: Host {} not known.'.format(tango_host))
        else:
            print('=' * 79)
            print('Known tango hosts:\n')
            for host in self._server_prefixes:
                print('{}'.format(host))
            print('=' * 79)

    def query_server(self, zmx_slot, verbose=True):
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
        param: verbose <boolean>
            Print information to console.
            default: True
        """
        tango_proxies = self._fetch_tango_proxies(zmx_slot)
        for servertype, serverentry in tango_proxies.items():
            # fetch_zmx and oms attributes
            for attr in sorted(self._motor_cache[servertype]):
                self._motor_cache[servertype][attr] = \
                    serverentry['device'].read_attribute(attr).value
                if isinstance(self._motor_cache[servertype][attr],
                              float):
                    self._motor_cache[servertype][attr] = \
                        round(self._motor_cache[servertype][attr], 4)
        # create 'loc' entries
        self._motor_cache['loc']['zmx_slot'] = zmx_slot
        self._motor_cache['loc']['zmx_device_name'] = tango_proxies['zmx']['device_name']
        self._motor_cache['loc']['oms_device_name'] = tango_proxies['oms']['device_name']

        if verbose:
            self.cache_info()

    def modify_cache(self, attribute, value, verbose=True):
        """
        Modifies cached motor values.

        param: attribute <str>
            attribute to modify
        param: value <all>
            new value for attribute
        param: verbose <boolean>
            Print information to console.
            default: True
        """
        for m_subg in self._motor_subgroups:
            for key in self._motor_cache[m_subg]:
                if key == attribute:
                    self._motor_cache[m_subg][key] = value
                    if verbose:
                        print('Inserted: {} {}'.format(attribute, value))
                    return
        if attribute in ['motorgroup', 'motorname']:
            self._database_entry[attribute] = value
            return
        raise Exception('{} not in cache (typo?)'.format(attribute))

    def write_cache_to_server(self, zmx_slot, update=True, verbose=True):
        """
        Write motor attributes from internal cache to ZMX/OMS tango servers.

        param: zmx_slot <int>
            number of the zmx slot. use numbers >16 for second crate
            on hzgpp05vme0:10000 (DMM)
        param: update_db <boolean> (optional)
            whether to update the database and cache automatically or not
            default: True
        param: verbose <boolean>
            Print information to console.
            default: True
        """
        tango_proxies = self._fetch_tango_proxies(zmx_slot)
        for servertype, serverentry in tango_proxies.items():
        # dump zmx and oms attributes
            for attr in sorted(self._motor_cache[servertype].keys()):
                value = self._motor_cache[servertype][attr]
                serverentry['device'].write_attribute(attr, value)
            if servertype == 'zmx':
                serverentry['device'].WriteEPROM()
                if verbose:
                    print('Write ZMX attrobutes to EPROM successful.')

        if update:
            if verbose:
                print('Updating cache and database:')
            self._motor_cache['loc']['zmx_slot'] = zmx_slot
            self._motor_cache['loc']['zmx_device_name'] = tango_proxies['zmx']['device_name']
            self._motor_cache['loc']['oms_device_name'] = tango_proxies['oms']['device_name']
            self.write_cache_to_database(overwrite_all=False, verbose=verbose)

    def cache_info(self):
        """
        Pretty prints internally cached values of a motor.
        """
        print('=' * 79)
        print('Cached attributes\n')
        print('motorgroup: {}'.format(self._database_entry['motorgroup']))
        print('motorname: {}\n'.format(self._database_entry['motorname']))
        for subgroup in self._motor_cache:
            for attr, value in self._motor_cache[subgroup].items():
                print('{:<9}: {:<23}: {}'.format(subgroup, attr, value))
        print('=' * 79)

    def write_cache_to_database(self, overwrite_all=False, verbose=True):
        """
        Write motor attributes into a h5 database on disk. Default behaviour
        for existing entries is to only overwrite 'loc' entries.
        Use 'overwrite_all' if other parameters should be overwritten as well.

        param: overwrite_all <boolean> (optional)
            Overwrites also motor attributes if true. Affects ony 'zmx' and
            'oms' subgroups. The 'loc' entries will always be written.
        param: verbose <boolean>
            Print information to console.
            default: True
        """
        if (self._database_entry['motorgroup'] and self._database_entry['motorname']) is None:
            raise Exception('Error motorname and motorgroup must be supplied.')
        p1 = self._database_entry['motorgroup']  # database directory path 1st level
        p2 = p1 + '/' + self._database_entry['motorname']  # database directory path 2nd level
        with h5py.File(self._motor_db_filepath, 'a') as h5db_file:
            # write attributes to database, iterate over subgroups
            for m_subg in self._motor_subgroups:
                p3 = p2 + '/' + m_subg  # database directory path 3rd level
                # writing in existing h5 entries will fail with a ValueError.
                # Hence for new entries:
                try:
                    zmx_group = h5db_file.create_group(p3)
                    for attr, value in self._motor_cache[m_subg].items():
                        zmx_group.create_dataset(attr, data=value)

                    for path in [p1, p2, p3]:  # update timestamps in database
                        h5db_file[path].attrs.create('last edit', str(datetime.now()), dtype="S19")

                # or, if the entry exists:
                except ValueError:
                    if overwrite_all:
                        if verbose:
                            print('Group already exists, Overwriting: {}'.format(p3))
                        for attr, value in self._motor_cache[m_subg].items():
                            del h5db_file[p3 + '/'+attr]
                            h5db_file[p3].create_dataset(attr, data=value)
                        for path in [p1, p2, p3]:  # update timestamps in database
                            h5db_file[path].attrs.create('last edit', str(datetime.now()), dtype="S19")
                    else:
                        if m_subg != 'loc':
                            if verbose:
                                print('Group already exists. No ovwrite_attrs flag  set. Skipping  {}.'.format(m_subg))
                            continue
                        else:
                            if verbose:
                                print('Group already exists, Overwriting: {}'.format(p3))
                            for attr, value in self._motor_cache['loc'].items():
                                del h5db_file[p2 + '/loc/'+attr]
                                h5db_file[p2 + '/loc'].create_dataset(attr, data=value)
                            for path in [p1, p2, p3]:  # update timestamps in database
                                h5db_file[path].attrs.create('last edit', str(datetime.now()), dtype="S19")
            h5db_file.close()

    def _retrieve_database_entries(self, *args, inclusive=False):
        """
        Fetches a list of entries in database based on search terms.

        param: search terms <str> (optional)
            Filters list for motorgroup or motorname members. if search term
            is omitted, the complete database list will be returned.
        param: inclusive <boolean>
            Filters either exact match of motorgroup - motorname pair or
            return every pair which includes any search term.
            default: False
        """
        args = [arg for arg in args if arg is not None]
        match = None if len(args) == 0 else args
        with h5py.File(self._motor_db_filepath, 'r') as h5db_file:
            db_entries = []
            for db_motorgroup in h5db_file.keys():
                for db_motorname in h5db_file[db_motorgroup].keys():
                    db_entries.append([db_motorgroup, db_motorname])
            h5db_file.close()
        if match:
            if inclusive:
                db_entries = [item for item in db_entries if item[0] in match or item[1] in match]
            else:
                for match_item in match:
                    db_entries = [item for item in db_entries if match_item in item]
        return db_entries

    def query_database(self, *args, **kwargs):
        """
        Queries motor attributes from h5 database and optionally stores them to
        the internal cache. If any parameter is omitted or not in database, an
        overview of the database contents will be printed instead.

        param: motorgroup <str> (optional)
            Name for the group to which the motor belongs to
            default: None
        param: motorname <str> (optional)
            Name of the motor
            default: None
        param: cache <boolean> (optional)
            Whether or not to save database entry to internal cache
            default: True
        param: verbose <boolean>
            Print information to console.
            default: True
        """
        cache = True if kwargs.get('cache') is None else kwargs.get('cache')
        verbose = True if kwargs.get('verbose') is None else kwargs.get('verbose')
        motorargs = [kwargs.get('motorgroup'), kwargs.get('motorname')]
        motorargs = [item for item in motorargs if item is not None]
        search = motorargs + list(args)
        # Fetch a list of all entries in database.
        db_entries = self._retrieve_database_entries(*search)
        # show list of known motors if motorgroup and motorname is empty or wrong
        if len(db_entries) != 1:
            if not verbose:
                return
            print('=' * 79)
            print('Ambiguous or search term(s): {}'.format(search))
            print('Based on the search term, the foloowing motor could be found:\n')
            for item in db_entries:
                print('{:<10} {}'.format(item[0], item[1]))
            print('=' * 79)
            return
        else:
            db_entries = db_entries[0]
        # Fetch attributes from database  and optionally write them to cache
        if verbose:
            print('=' * 79)
            print('{} {} attributes\n'.format(db_entries[0], db_entries[1]))
        p1 = db_entries[0]  # database directory path 1st level
        p2 = p1 + '/' + db_entries[1]  # database directory path 2nd level
        with h5py.File(self._motor_db_filepath, 'r') as h5db_file:
            for m_subg in self._motor_subgroups:
                p3 = p2 + '/' + m_subg  # database directory path 3rd level
                for attr in self._motor_cache[m_subg].keys():
                    value = h5db_file[p3 + '/'+attr].value
                    if verbose:
                        print('{:<9}: {:<23}: {}'.format(m_subg, attr, value))
                    if cache:
                        self._motor_cache[m_subg][attr] = h5db_file[p3 + '/'+attr].value
                        self._database_entry['motorgroup'] = db_entries[0]
                        self._database_entry['motorname'] = db_entries[1]
            h5db_file.close()
        if verbose:
            if cache:
                print('\nMotor parameters copied to local cache.')
            print('=' * 79)

    def check_consistency(self, *args, **kwargs):
        """
        Checks if database entry match with corresponding tango server entry.
        Work only on current tango_host.

        param: motorgroup <str> (optional)
            Name for the group to which the motor belongs to
            default: None
        param: motorname <str> (optional)
            Name of the motor
            default: None
        param: verbose <boolean>
            Print information to console.
            default: True
        """
        verbose = True if kwargs.get('verbose') is None else kwargs.get('verbose')
        motorargs = [kwargs.get('motorgroup'), kwargs.get('motorname')]
        motorargs = [item for item in motorargs if item is not None]
        search = motorargs + list(args)
        db_entries = self._retrieve_database_entries(*search, inclusive=True)
        delta = []
        no_delta = []
        with h5py.File(self._motor_db_filepath, 'r') as h5db_file:
            for (db_motorgroup, db_motorname) in db_entries:
                p1 = db_motorgroup  # database directory path 1st level
                p2 = p1 + '/' + db_motorname  # database directory path 2nd level
                zmx_server_name = h5db_file[p2 + '/loc/zmx_device_name'].value
                oms_server_name = h5db_file[p2 + '/loc/oms_device_name'].value
                zmx_server = tango.DeviceProxy(zmx_server_name)
                oms_server = tango.DeviceProxy(oms_server_name)
                if self._tango_host not in h5db_file[p2 + '/loc/zmx_device_name'].value:
                    continue
                p3 = p2 + '/zmx'  # database directory path 3rd level
                diff = False
                for attr in self._motor_cache['zmx'].keys():
                    db_value = h5db_file[p3 + '/' + attr].value
                    tg_value = zmx_server.read_attribute(attr).value
                    if isinstance(tg_value, float):
                        tg_value = round(tg_value, 4)
                    if db_value != tg_value:
                        delta.append([db_motorgroup, db_motorname, attr, db_value, tg_value])
                        diff = True
                p3 = p2 + '/oms'  # database directory path 3rd level
                for attr in self._motor_cache['oms'].keys():
                    db_value = h5db_file[p3 + '/' + attr].value
                    tg_value = oms_server.read_attribute(attr).value
                    if isinstance(tg_value, float):
                        tg_value = round(tg_value, 4)
                    if db_value != tg_value:
                        delta.append([db_motorgroup, db_motorname, attr, db_value, tg_value])
                        diff = True
                if not diff:
                    no_delta.append([db_motorgroup, db_motorname])
            if verbose:
                print('=' * 79)
                for motor in no_delta:
                    print('[OK] {:<10} {:<20} No differences found.'.format(motor[0], motor[1]))
                if len(delta) != 0:
                    print('-' * 79 + '\n')
                    print('Differences found in:')
                    print('{:<30}|{:<20}|{:<20}'.format('Axis name', 'Database value', 'Tango value'))
                    print('-' * 30 + '+' + '-' * 20 + '+' + '-' * 20)
                    for diff in delta:
                        ax_name = '({}/{}/{})'.format(diff[0], diff[1], diff[2])
                        print('{:<30}|{:<20}|{:<20}'.format(ax_name, diff[3], diff[4]))
                print('=' * 79)
            h5db_file.close()


if __name__ == '__main__':
    TM = TangoMotorDb()