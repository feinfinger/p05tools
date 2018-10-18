#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Sep 11 12:35:30 2018

@author: fwilde
"""

import sys
from PyQt5 import QtGui, QtCore, QtWidgets
import pyqtgraph as pg
import tango
import numpy
import time
import datetime
import os


class QbpmMonitor(QtGui.QWidget):
    """
    QBPM monitor GUI for P05 beamline. Displays Oxford i404 beam position and average current as
    well as PETRA III ring current which are polled logged by an instance of the Qbpm() class.
    Additionally it is possible to let this monitor regulate the vertical beam position in a feedback
    loop.
    """
    def __init__(self, qbpm_instance, simulate_feedback=False):
        """
        Set up GUI and initialize class variables.
        :param qbpm_instance: Qbpm() class instance
        """
        super(QbpmMonitor, self).__init__()
        self.qbpm = qbpm_instance
        self.title = self.qbpm.address
        self.posx_target = 0
        self.posz_target = 0
        self.avgcurr_target = 0
        self.qbpm.frequency = 5.0  # in Hz
        self.qbpm.backlog = 120  # in s
        self.polling = False
        self._generator_poll = None
        self._timerId_poll = None
        self.feedback = False
        self.feedback_threshold = 5E-9
        self._generator_feedback = None
        self._timerId_feedback = None
        self.dcm_bragg_tserver = tango.DeviceProxy('hzgpp05vme0:10000/dcm_bragg')
        self.dcm_bragg_angle = self.dcm_bragg_tserver.Position
        self.dcm_pitch_tserver = tango.DeviceProxy('hzgpp05vme0:10000/dcm_xtal2_pitch')
        self.heartbeat = time.time()
        self.feedback_file = '/tmp/qbpmfeedback.run'
        if os.path.isfile(self.feedback_file):
            os.remove(self.feedback_file)
        self.cycle = 0
        self.feedback_triggered = False
        self.simulate_feedback = simulate_feedback
        self.dcm_step_backlash = self.dcm_pitch_tserver.read_attribute('StepBacklash').value

        ################################################################################################################
        # initUI

        # labels
        self.poll_label = QtGui.QLabel("poll")
        self.feedback_label = QtGui.QLabel("feedback")
        self.ll_label = QtGui.QLabel("backlog (s)")
        self.freq_label = QtGui.QLabel("frequency")
        self.sensitivity_label = QtGui.QLabel("sensitivity")
        self.filter_label = QtGui.QLabel("lowpass filter")
        self.log_label = QtGui.QLabel("log to file")
        self.pitch_label = QtGui.QLabel("DCM pitch: {:.9f}".format(self.dcm_pitch_tserver.Position))
        # quit button
        qbtn = QtGui.QPushButton('Quit', self)
        qbtn.clicked.connect(QtCore.QCoreApplication.instance().quit)
        # reset button
        qbtn.resize(qbtn.sizeHint())
        reset_btn = QtGui.QPushButton('Reset', self)
        reset_btn.clicked.connect(self.qbpm.reset_logs)
        reset_btn.resize(qbtn.sizeHint())
        # poll button
        self.rbtn = QtGui.QPushButton(self)
        self.rbtn.clicked.connect(self.toggle_polling)
        self.rbtn.resize(qbtn.sizeHint())
        self.rbtn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))
        # feedback button
        self.fbtn = QtGui.QPushButton(self)
        self.fbtn.clicked.connect(self.toggle_feedback)
        self.fbtn.resize(qbtn.sizeHint())
        self.fbtn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))
        # backlog text field
        self.lltext = QtGui.QLineEdit(str(self.qbpm.backlog))
        self.lltext.setValidator(QtGui.QIntValidator())
        self.lltext.setMaxLength(6)
        self.lltext.returnPressed.connect(self.change_backlog)
        # frequency text field
        self.ftext = QtGui.QLineEdit(str(self.qbpm.frequency))
        self.ftext.setValidator(QtGui.QDoubleValidator())
        self.ftext.setMaxLength(6)
        self.ftext.returnPressed.connect(self.change_frequency)
        # sensititvity slider
        self.sslider = QtGui.QSlider(self)
        self.sslider.setOrientation(QtCore.Qt.Horizontal)
        self.sslider.setMinimum(1)
        self.sslider.setMaximum(100)
        self.sslider.setTickPosition(QtGui.QSlider.TicksBothSides)
        self.sslider.setTickInterval(10)
        self.sslider.setSingleStep(1)
        self.sslider.setValue(self.qbpm.sensitivity)
        self.sslider.valueChanged.connect(self._set_sensitivity)
        # filter slider
        self.fslider = QtGui.QSlider(self)
        self.fslider.setOrientation(QtCore.Qt.Horizontal)
        self.fslider.setMinimum(1)
        self.fslider.setMaximum(1000)
        self.fslider.setTickPosition(QtGui.QSlider.TicksBothSides)
        self.fslider.setTickInterval(100)
        self.sslider.setSingleStep(1)
        self.fslider.setValue(self.qbpm.filter)
        self.fslider.valueChanged.connect(self._set_filter)
        # log button
        self.lbutton = QtGui.QRadioButton(self)
        self.lbutton.setChecked(True)

        r, g, b, w = [255, 0, 0], [0, 255, 0], [0, 0, 255], [150, 150, 150]
        fill_color = pg.mkColor([0, 255, 0, 100])
        self.curves = {}
        log_pen = pg.mkPen(w, width=1, style=QtCore.Qt.SolidLine)
        avg_pen = pg.mkPen(r, width=3, style=QtCore.Qt.SolidLine)
        target_pen = pg.mkPen(g, width=1, style=QtCore.Qt.SolidLine)
        sensitivity_pen = pg.mkPen(fill_color, width=1, style=QtCore.Qt.SolidLine)
        fill_pen = pg.mkPen(fill_color, width=100, style=QtCore.Qt.SolidLine)
        petra_pen = pg.mkPen(w, width=3, style=QtCore.Qt.SolidLine)
        # define plot font
        font = QtGui.QFont()
        font.setPixelSize(16)
        # make PlotWidgets
        self.plot_main = pg.GraphicsLayoutWidget()
        self.avgcurr_timeaxis = TimeAxisItem(orientation='bottom')
        self.plot_avgcurr = self.plot_main.addPlot(title='avg. current', row=0, col=0,
                                                   axisItems={'bottom': self.avgcurr_timeaxis})
        self.petracurr_timeaxis = TimeAxisItem(orientation='bottom')
        self.plot_petracurrent = self.plot_main.addPlot(title='PETRA beam current', row=0, col=1,
                                                        axisItems={'bottom': self.petracurr_timeaxis})
        self.plot_main.nextRow()
        self.posx_timeaxis = TimeAxisItem(orientation='bottom')
        self.plot_posx = self.plot_main.addPlot(title='x-position', row=1, col=0,
                                                axisItems={'bottom': self.posx_timeaxis})
        self.posy_timeaxis = TimeAxisItem(orientation='bottom')
        self.plot_posz = self.plot_main.addPlot(title='z-position', row=1, col=1,
                                                axisItems={'bottom': self.posy_timeaxis})
        # assign qbpm data to styles and PlotWidgets
        styles = {'avgcurr_log': (self.plot_avgcurr, log_pen),
                  'avgcurr_filter_log': (self.plot_avgcurr, avg_pen),
                  'avgcurr_target_log': (self.plot_avgcurr, target_pen),
                  'posx_log': (self.plot_posx, log_pen),
                  'posx_filter_log': (self.plot_posx, avg_pen),
                  'posx_target_log': (self.plot_posx, target_pen),
                  'posz_log': (self.plot_posz, log_pen),
                  'posz_filter_log': (self.plot_posz, avg_pen),
                  'posz_target_log': (self.plot_posz, target_pen),
                  'posz_sens_low_log': (self.plot_posz, sensitivity_pen),
                  'posz_sens_high_log': (self.plot_posz, sensitivity_pen),
                  'petracurrent_log': (self.plot_petracurrent, petra_pen)
                  }
        # plot curves
        for log_array, style in styles.items():
            # self.curves[key] = style[0].plot(self.qbpm.log_arrays[key], pen=style[1], symbol='o')
            self.curves[log_array] = style[0].plot(self.qbpm.log_time, self.qbpm.log_arrays[log_array], pen=style[1])
        # self.fill = pg.FillBetweenItem(curve1=self.curves['posz_sens_low_log'],
        #                                curve2=self.curves['posz_sens_high_log'], pen=fill_pen)
        # self.plot_posz.addItem(self.fill)
        # set axis properties
        for log_plot in [self.plot_avgcurr, self. plot_posx, self.plot_posz, self.plot_petracurrent]:
            log_plot.getAxis("bottom").tickFont = font
            log_plot.getAxis("bottom").setStyle(tickTextOffset=20)
            log_plot.getAxis("left").tickFont = font
            log_plot.getAxis("left").setStyle(tickTextOffset=20)
            log_plot.getAxis("left").setWidth(100)
            log_plot.getAxis("bottom").setGrid(100)
            log_plot.getAxis("left").setGrid(100)

        # Create a grid layout to manage the widgets size and position
        layout = QtGui.QGridLayout()
        self.setLayout(layout)

        # Add widgets to the layout in their proper positions
        layout.addWidget(self.poll_label, 0, 0)
        layout.addWidget(self.feedback_label, 1, 0)
        layout.addWidget(self.ll_label, 3, 0)
        layout.addWidget(self.freq_label, 4, 0)
        layout.addWidget(self.sensitivity_label, 5, 0)
        layout.addWidget(self.filter_label, 6, 0)
        layout.addWidget(self.log_label, 7, 0)
        layout.addWidget(self.rbtn, 0, 1)   # button goes in lower-left
        layout.addWidget(self.fbtn, 1, 1)   # button goes in lower-left
        layout.addWidget(reset_btn, 2, 1)   # button goes in lower-left
        layout.addWidget(self.lltext, 3, 1)   # text edit goes in middle-left
        layout.addWidget(self.ftext, 4, 1)   # text edit goes in middle-left
        layout.addWidget(self.sslider, 5, 1)
        layout.addWidget(self.fslider, 6, 1)
        layout.addWidget(self.lbutton, 7, 1)
        layout.addWidget(self.pitch_label, 8, 0, 1, 2)   # button goes in lower-left
        layout.addWidget(qbtn, 9, 0, 1, 2)   # button goes in lower-left
        layout.addWidget(self.plot_main, 0, 2, 10, 1)

        layout.setColumnStretch(0, 0.1)
        layout.setColumnStretch(1, 0.1)
        layout.setColumnStretch(2, 1)

        # Display the widget as a new window
        self.setWindowTitle(self.title)
        self.show()

    def _plot_update(self):
        """
        Updates plot window with current values from Qbpm() class instance.
        :return: None
        """
        omit_log = ['sens_log']
        for log_group, log_arrays in self.qbpm.log_names.items():
            for log_array in log_arrays:
                if log_array not in omit_log:
                    self.curves[log_array].setData(self.qbpm.log_time, self.qbpm.log_arrays[log_array],clear=True)
        # self.fill.setCurves(self.curves['posz_sens_low_log'], self.curves['posz_sens_high_log'])

    def toggle_polling(self):
        """
        Toggles polling on or off. Connected to Poll button.
        :return: None
        """
        self.polling = not self.polling
        if not self.polling:
            # print('In toggle polling')
            self._stop_loop_feedback()
        self._start_loop_poll() if self.polling else self._stop_loop_poll()

    def _read_qbpm_loop(self):
        """
        Main qbpm update loop. Reads new QBPM / ring current values and updates plots.
        Generator for Qt timer method.
        :return: None
        """
        while True:
            self.qbpm.read_qbpm()
            self._plot_update()
            self.pitch_label.setText("DCM pitch: {:.9f}".format(self.dcm_pitch_tserver.Position))
            if self.lbutton.isChecked():
                fname = 'qbpm_log.csv'
                if not os.path.isfile(fname):
                    with open(fname, 'a') as f:
                        f.write('timestamp qbpm_avgcurr qbpm_x qbpm_z petra_curr\n')
                with open(fname, 'a') as f:
                    t = self.qbpm.log_time[-1]
                    a = self.qbpm.log_arrays['avgcurr_log'][-1]
                    x = self.qbpm.log_arrays['posx_log'][-1]
                    z = self.qbpm.log_arrays['posz_log'][-1]
                    p = self.qbpm.log_arrays['petracurrent_log'][-1]
                    l = '{} {} {} {} {}\n'.format(t, a, x ,z , p)
                    f.write(l)
            yield

    def _start_loop_poll(self):
        """
        Initializes Qt timer method for polling routine and switches Play button icon.
        :return: None
        """
        self._stop_loop_poll()  # Stop any existing timer
        self._generator_poll = self._read_qbpm_loop()  # Start the loop
        self._timerId_poll = self.startTimer(0)   # This is the idle timer
        self.rbtn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaPause))

    def _stop_loop_poll(self):  # Connect to Stop-button clicked()
        """
        Stops Qt timer method for polling routine and switches Play button icon.
        :return: None
        """
        if self._timerId_poll is not None:
            self.killTimer(self._timerId_poll)
        self._generator_poll = None
        self._timerId_poll = None
        self.rbtn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))
        self.heartbeat = time.time()

    def toggle_feedback(self):
        """
        Toggles DCM feedback. Connected tofeedback button.
        :return: None
        """
        self.feedback = not self.feedback
        if self.feedback:
            self._start_loop_feedback()
        else:
            # print('In toggle feedback')
            self._stop_loop_feedback()

    def _set_feedback_loop(self):
        """
        Main feedback loop. Calculates deviation of the vertical QBPM position from target value and moves
        DCM pitch accordingly. Generator for Qt timer method.
        :return: None
        """
        while True:
            interval = int(self.qbpm.filter / 20)
            if self.qbpm.log_arrays['avgcurr_log'][-1] < self.feedback_threshold:
                print('intensity too low.')
                self._stop_loop_feedback()
            current_pos = self.qbpm.log_arrays['posz_filter_log'][-1]
            target = self.qbpm.posz_target
            corr_factor = 0.2
            bandwidth = 0.003 * float(self.qbpm.sensitivity/100)
            if not ((target - bandwidth) < current_pos < (target + bandwidth)):
                corr_angle = -((current_pos - target) * corr_factor)/self.qbpm.distance
                if self.cycle == interval:
                    print('Moving pitch: {}'.format(corr_angle))
                    dcm_curr_pitchpos = self.dcm_pitch_tserver.Position
                    dcm_target_pitchpos = dcm_curr_pitchpos + corr_angle
                    if not self.simulate_feedback:
                        self.dcm_pitch_tserver.write_attribute('StepBacklash',0)
                        self.dcm_pitch_tserver.write_attribute('Position', dcm_target_pitchpos)
                        self.dcm_pitch_tserver.write_attribute('StepBacklash',self.dcm_step_backlash)
                    self.cycle = 0
            self.cycle = 0 if self.cycle >= interval else self.cycle + 1
            yield

    def _start_loop_feedback(self):
        """
        Initializes Qt timer method for feedback routine and switches Play button icon.
        :return: None
        """
        self._stop_loop_feedback()  # Stop any existing timer
        self._generator_feedback = self._set_feedback_loop()  # Start the loop
        self._timerId_feedback = self.startTimer(0)   # This is the idle timer
        self.fbtn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaPause))
        # tell qbpm class that feedback is on
        self.qbpm.feedback_on = True
        self.posx_target = self.qbpm.log_arrays['posx_target_log'][-1]
        self.posz_target = self.qbpm.log_arrays['posz_target_log'][-1]
        self.avgcurr_target = self.qbpm.log_arrays['avgcurr_target_log'][-1]
        self.qbpm.posx_target = self.posx_target
        self.qbpm.posz_target = self.posz_target
        self.qbpm.avgcurr_target = self.avgcurr_target
        self.dcm_bragg_angle = self.dcm_bragg_tserver.Position

    def _stop_loop_feedback(self):  # Connect to Stop-button clicked()
        """
        Stops Qt timer method for feedback routine and switches Play button icon.
        :return: None
        """
        if self._timerId_feedback is not None:
            self.killTimer(self._timerId_feedback)
        self._generator_feedback = None
        self._timerId_feedback = None
        self.fbtn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))
        self.qbpm.feedback_on = False

    def _set_sensitivity(self, value):
        """
        Sets feedback sensitivity.

        :param value: <int> Connected to slider
        :return: None
        """
        self.qbpm.sensitivity = value

    def _set_filter(self, value):
        """
        Sets feedback sensitivity.

        :param value: <float> Connected to slider
        :return: None
        """
        self.qbpm.filter = value

    def timerEvent(self, event):
        """
        Main timer event function. This is called every time the GUI is idle.
        :param event: Connected to timerEvent
        :return: None
        """
        self.ext_fb_trigger()
        if self._check_pulse():
            if self._generator_poll is None:
                if self._generator_feedback is not None:
                    # print('In timerEvent 2')
                    self._stop_loop_feedback()
                return
            try:
                next(self._generator_poll)  # Run the next iteration
                if self._generator_feedback is None:
                    return
                try:
                    next(self._generator_feedback)
                except Exception as e:
                    print(e)
                    self._stop_loop_feedback()
            except StopIteration:
                # print('In timerEvent 5')
                self._stop_loop_feedback()  # Iteration has finished, kill the timer
                self._stop_loop_poll()  # Iteration has finished, kill the timer

    def ext_fb_trigger(self):
        """
        Checks if feedback trigger file exists. If the file exists, feedback will be toggled and the file
        will be deleted.
        :return: None
        """
        if os.path.isfile(self.feedback_file):
            self.toggle_feedback()
            os.remove(self.feedback_file)

    def _check_pulse(self):
        """
        This function checks if an update of the log_arrays is due.
        :return: boolean
        """
        timedelta = time.time() - self.heartbeat
        update_delay = float(1/self.qbpm.frequency)
        time_to_update = False
        if timedelta > update_delay:
            time_to_update = True
            self.heartbeat = time.time()
        return time_to_update

    def change_backlog(self):
        """
        Connected to backlog input field of the GUI. Triggers change of the number of backlog values in the
        Qbom() class instance.
        :return:
        """
        if not self.lltext.text():
            return
        backlog = int(self.lltext.text())
        self.qbpm.change_backlog(backlog)
        self.lltext.setText(str(self.qbpm.backlog))

    def change_frequency(self):
        """
        Connected to freuqncey input field of the GUI. Triggers change of the polling frequency
        in the Qbpm() class instance.
        :return:
        """
        if not self.ftext.text():
            return
        frequency = float(self.ftext.text())
        if frequency > 6.0:
            frequency = 6.0
        self.qbpm.change_frequency(frequency)
        self.ftext.setText(str(self.qbpm.frequency))


class Qbpm:
    """
    Qbpm class to work with QbpmMonitor class. Each QBPM instance creates these arrays to log:
        - QBPM horizontal position
        - QBPM vertical positions
        - QBPM average current
        - PETRA III ring current
        - target values of all logged values (used for monochromator feedback)
        - low pass filter values for all logged values (used for monochromator feedback)
        - current time (to plot above values against)

    Each update rolls all arrays by one and adds the current value at the end of the array.
    """
    def __init__(self, address, distance):
        """
        Initialize class variables and set all array to sensible initial values.
        :param address: <str> Tango server address of the QBPM.
        :param distance: <float> Distance of the monochromator to the QBPM in metre.
        """

        self.address = address  # Tango server address
        self.tserver = tango.DeviceProxy(address)
        self.log_arrays = {}
        self.distance = distance  # distance of the monochromator to the QBPM
        self.petra = tango.DeviceProxy('hzgpp05vme1:10000/PETRA/GLOBALS/keyword')
        self.frequency = 5  # update freuqncy in Hz
        self.backlog = 120  # backlog length in s
        self.log_length = self.calc_log_length(self.backlog, self.frequency)
        self.log_names = {'log_vals': ['posx_log', 'posz_log', 'avgcurr_log', 'petracurrent_log'],
                          'log_filter': ['posx_filter_log', 'posz_filter_log', 'avgcurr_filter_log'],
                          'log_target': ['posx_target_log', 'posz_target_log', 'avgcurr_target_log'],
                          'log_sens': ['sens_log', 'posz_sens_low_log', 'posz_sens_high_log']
                          }
        self.log_time = numpy.zeros(self.log_length)
        self.reset_logs()  # initialize log_arrays with appropriate log_length
        self.box_length = 40  # rolling average over box_length values
        self.posx_target = 0  # target horizontal position during feedback
        self.posz_target = 0  # target vertical position during feedback
        self.avgcurr_target = 0  # target average QBPM current during feedback
        self.feedback_on = False  # sets target logging behaviour
        self.sensitivity = 10
        self.filter = 500

    def read_qbpm(self):
        """
        Update all class arrays: QBPM horizontal and vertical position, QBPM average current, PETRA III ring current,
        target positions and moving average.
        :return: None
        """
        # roll all log arrays
        for key, names in self.log_names.items():
            for name in names:
                self.log_arrays[name][:] = numpy.roll(self.log_arrays[name], -1)
        self.log_time[:] = numpy.roll(self.log_time, -1)
        # query qbpm and petra current, append to log array
        try:
            bc = self.petra.BeamCurrent
        except tango.DevFailed:
            bc = numpy.nan
        try:
            pac = self.tserver.read_attribute('PosAndAvgCurr').value
        except tango.DevFailed:
            pac = numpy.array([numpy.nan, numpy.nan, numpy.nan])
        server_query = numpy.append(pac, bc)
        for n, key in enumerate(self.log_names['log_vals']):
            self.log_arrays[key][-1] = server_query[n]
        # calculate moving average and append to log array
        for n, key in enumerate(self.log_names['log_filter']):
            a = 1*10**-(3*float(self.filter)/1000)
            last_logval = self.log_arrays[self.log_names['log_vals'][n]][-1]
            last_filterval = self.log_arrays[key][-2]
            filter = last_logval * a + (1 - a) * last_filterval
            self.log_arrays[key][-1] = filter
        targets = [self.posx_target,  self.posz_target, self.avgcurr_target]
        # append current target position (depends on feedback)
        for n, key in enumerate(self.log_names['log_target']):
            if self.feedback_on:
                self.log_arrays[key][-1] = targets[n]
            else:
                last_mvg_avg = self.log_arrays[self.log_names['log_filter'][n]][-1]
                self.log_arrays[key][-1] = last_mvg_avg
        # append current sensitivity to log arrays
        sensitivity = 0.003 * float(self.sensitivity/100)
        low_sens = self.posz_target - sensitivity
        high_sens = self.posz_target + sensitivity
        sens_vals = numpy.array([sensitivity, low_sens, high_sens])
        for n, key in enumerate(self.log_names['log_sens']):
            if self.feedback_on:
                self.log_arrays[key][-1] = sens_vals[n]
            else:
                self.log_arrays[key][-1] = numpy.nan

        # reset target position if feedback is off
        if not self.feedback_on:
            self.posx_target = self.log_arrays['posx_filter_log'][-1]
            self.posz_target = self.log_arrays['posz_filter_log'][-1]
            self.avgcurr_target = self.log_arrays['avgcurr_filter_log'][-1]
        # append unix timestamp to log_time
        self.log_time[-1] = self.timestamp()
        # append sens_log value

    def change_log_length(self, log_length):
        """
        Changes log length of all arrays. Tries to keep already measured values in place.
        :param log_length: <int> new log length
        :return: None
        """
        len_diff = abs(self.log_length - log_length)
        if log_length > self.log_length:
            for log_group in self.log_names.values():
                for log_array in log_group:
                    tmparr = numpy.full(log_length, self.log_arrays[log_array][0])  # generate tmparr with first value from array
                    tmparr[-self.log_arrays[log_array].size:] = self.log_arrays[log_array]  # fill end with current array
                    self.log_arrays[log_array] = tmparr
            tmparr = numpy.zeros(log_length)
            tmparr[:len_diff] = numpy.linspace(self.log_time[0] - len_diff/self.frequency,
                                                       self.log_time[0], len_diff)
            tmparr[-self.log_time.size:] = self.log_time
            self.log_time = tmparr
        else:
            for log_group in self.log_names.values():
                for log_array in log_group:
                    tmparr = numpy.zeros(log_length)
                    tmparr[:] = self.log_arrays[log_array][-log_length:]
                    self.log_arrays[log_array] = tmparr
            tmparr = numpy.zeros(log_length)
            tmparr[:] = self.log_time[-log_length:]
            self.log_time = tmparr
        self.log_length = log_length

    def calc_log_length(self, backlog, frequency):
        """
        Convert update frequency and backlog time into array length
        :param backlog: <float> backlog time in seconds
        :param frequency: <float> update frequency in Hz
        :return: <int> backlog array length
        """
        return int(numpy.ceil(backlog * frequency))

    def change_backlog(self, backlog):
        """
        Changes backlog length. If the calculated backlog length is smaller than the box_length for the rolling average
        backlog length will be set equal to the box_length.
        :param backlog: <float> backlog length in seconds
        :return: None
        """
        min_backlog = int(numpy.ceil(self.box_length / self.frequency))
        if backlog < min_backlog:
            backlog = min_backlog
        log_length = self.calc_log_length(backlog, self.frequency)
        self.backlog = backlog
        self.change_log_length(log_length)

    def change_frequency(self, frequency):
        """
        Change backlog length if the update frequency hass changed
        :param frequency: <float> update frequency in Hz
        :return: None
        """
        self.frequency = frequency
        self.change_backlog(self.backlog)

    def reset_logs(self):
        """
        Sets all log arrays to a current value.
        :return:  None
        """
        # reset log arrays
        try:
            bc = self.petra.BeamCurrent
        except:
            bc = numpy.nan
        try:
            pac = self.tserver.read_attribute('PosAndAvgCurr').value
        except:
            pac = numpy.array([numpy.nan, numpy.nan, numpy.nan])
        server_query = numpy.append(pac, bc)
        for log_group, log_arrays in self.log_names.items():
            omit_group = ['log_sens']
            if log_group not in omit_group:
                for n, log_array in enumerate(log_arrays):
                    self.log_arrays[log_array] = numpy.full(self.log_length, server_query[n])
        # reset sensitivity log
        for log_array in self.log_names['log_sens']:
            self.log_arrays[log_array] = numpy.full(self.log_length, numpy.nan)
        # reset time array
        length = self.log_time.size
        t0 = self.timestamp() - self.backlog
        t1 = self.timestamp()
        self.log_time = numpy.linspace(t0, t1, length)

    def timestamp(self):
        """
        Generate a timestamp in unix time.
        :return: <int> timestamp
        """
        return time.time()


class TimeAxisItem(pg.AxisItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setLabel(text='Time', units=None)
        self.enableAutoSIPrefix(False)

    def tickStrings(self, values, scale, spacing):
        return [datetime.datetime.fromtimestamp(value).strftime("%H:%M:%S") for value in values]


if __name__ == '__main__':
    # qbpm1 = Qbpm('hzgpp05vme0:10000/p05/i404/exp.01', 2)
    qbpm2 = Qbpm('hzgpp05vme0:10000/p05/i404/exp.02', 7)
    app = QtGui.QApplication(sys.argv)
    qbpm_mon = QbpmMonitor(qbpm2, simulate_feedback=True)
    sys.exit(app.exec_())
