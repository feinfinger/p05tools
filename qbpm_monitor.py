3#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Sep 11 12:35:30 2018

@author: fwilde
"""

import sys
from PyQt5 import QtGui, QtCore, QtWidgets # (the example applies equally well to PySide)
import pyqtgraph as pg
import tango
import numpy
import time
import datetime


class QbpmMonitor(QtGui.QWidget):
    def __init__(self, address, distance):
        super(QbpmMonitor, self).__init__()
        self.title = address
        self.posx_target = 0
        self.posz_target = 0
        self.avgcurr_target = 0
        self.qbpm = qbpm(address, distance)
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

        self.initUI()

    def initUI(self):
        ## Create some widgets to be placed inside
        # labels
        self.poll_label = QtGui.QLabel("poll")
        self.feedback_label = QtGui.QLabel("feedback")
        self.ll_label = QtGui.QLabel("backlog (s)")
        self.freq_label = QtGui.QLabel("frequency")
        self.pitch_label = QtGui.QLabel("DCM pitch: {}".format(self.dcm_pitch_tserver.Position))
        # quit button
        qbtn = QtGui.QPushButton('Quit', self)
        qbtn.clicked.connect(QtCore.QCoreApplication.instance().quit)
        # reset button
        qbtn.resize(qbtn.sizeHint())
        reset_btn = QtGui.QPushButton('Reset', self)
        reset_btn.clicked.connect(self.reset_logs)
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
#        self.listw = QtGui.QListWidget()
        r, g, w = [255, 0, 0], [0, 255, 0], [255, 255, 255]
        self.curves = {}
        log_pen = pg.mkPen('w', width=1, style=QtCore.Qt.SolidLine)
        avg_pen = pg.mkPen('r', width=3, style=QtCore.Qt.SolidLine)
        target_pen = pg.mkPen('g', width=1, style=QtCore.Qt.DashLine)
        petra_pen = pg.mkPen('w', width=3, style=QtCore.Qt.SolidLine)
        pens = [log_pen, avg_pen, target_pen]
        # define plot font
        font=QtGui.QFont()
        font.setPixelSize(16)
        # make PlotWidgets
        self.plot_main = pg.GraphicsLayoutWidget()
        self.avgcurr_timeaxis = TimeAxisItem(orientation='bottom')
        self.plot_avgcurr = self.plot_main.addPlot(title='avg. current', row=0, col=0, axisItems={'bottom': self.avgcurr_timeaxis})
        self.petracurr_timeaxis = TimeAxisItem(orientation='bottom')
        self.plot_petracurrent = self.plot_main.addPlot(title='PETRA beam current', row=0, col=1, axisItems={'bottom': self.petracurr_timeaxis})
#        self.plot_main.nextRow()
        self.posx_timeaxis = TimeAxisItem(orientation='bottom')
        self.plot_posx = self.plot_main.addPlot(title='x-position', row=1, col=0, axisItems={'bottom': self.posx_timeaxis})
        self.posy_timeaxis = TimeAxisItem(orientation='bottom')
        self.plot_posz = self.plot_main.addPlot(title='z-position', row=1, col=1, axisItems={'bottom': self.posy_timeaxis})
        # assign qbpm data tp styles to PlotWidgets
        styles = {'avgcurr_log': (self.plot_avgcurr, log_pen),
                  'avgcurr_mvavg_log': (self.plot_avgcurr, avg_pen),
                  'avgcurr_target_log': (self.plot_avgcurr, target_pen),
                  'posx_log': (self.plot_posx, log_pen),
                  'posx_mvavg_log': (self.plot_posx, avg_pen),
                  'posx_target_log': (self.plot_posx, target_pen),
                  'posz_log': (self.plot_posz, log_pen),
                  'posz_mvavg_log': (self.plot_posz, avg_pen),
                  'posz_target_log': (self.plot_posz, target_pen),
                  'petracurrent_log': (self.plot_petracurrent, petra_pen)
                  }
        # plot curves
        for key, style in styles.items():
            #self.curves[key] = style[0].plot(self.qbpm.log_arrays[key], pen=style[1], symbol='o')
            self.curves[key] = style[0].plot(self.qbpm.log_arrays[key], pen=style[1])
            style[0].getAxis("bottom").tickFont = font
            style[0].getAxis("bottom").setStyle(tickTextOffset=20)
            style[0].getAxis("left").tickFont = font
            style[0].getAxis("left").setStyle(tickTextOffset=20)
            style[0].getAxis("left").setWidth(100)
            style[0].getAxis("bottom").setGrid(100)
            style[0].getAxis("left").setGrid(100)
      
        #Create a grid layout to manage the widgets size and position
        layout = QtGui.QGridLayout()
        self.setLayout(layout)

        # Add widgets to the layout in their proper positions
        layout.addWidget(self.poll_label, 0, 0)
        layout.addWidget(self.feedback_label, 1, 0)
        layout.addWidget(self.ll_label, 3, 0)
        layout.addWidget(self.freq_label, 4, 0)
        layout.addWidget(self.rbtn, 0, 1)   # button goes in lower-left
        layout.addWidget(self.fbtn, 1, 1)   # button goes in lower-left
        layout.addWidget(reset_btn, 2, 1)   # button goes in lower-left
        layout.addWidget(self.lltext, 3, 1)   # text edit goes in middle-left
        layout.addWidget(self.ftext, 4, 1)   # text edit goes in middle-left
        layout.addWidget(self.pitch_label, 8, 0, 1, 2)   # button goes in lower-left
        layout.addWidget(qbtn, 9, 0, 1, 2)   # button goes in lower-left
        layout.addWidget(self.plot_main, 0,2,10,1)

        layout.setColumnStretch(0,0.1)
        layout.setColumnStretch(1,0.1)
        layout.setColumnStretch(2,1)

        # Display the widget as a new window
        self.setWindowTitle(self.title)
        self.show()

    def plot_update(self):
        for key, names in self.qbpm.log_names.items():
            for name in names:
                self.curves[name].setData(self.qbpm.log_xarr, self.qbpm.log_arrays[name])

    def reset_logs(self):
        self.qbpm.reset_logs()

    def toggle_polling(self):
        self.polling = not self.polling
        if not self.polling: self.stop_loop_feedback()
        self.start_loop_poll() if self.polling else self.stop_loop_poll()

    def read_qbpm_loop(self):
        while True:
            self.qbpm.read_qbpm()
            self.plot_update()
            self.pitch_label.setText("DCM pitch: {}".format(self.dcm_pitch_tserver.Position))
            yield

    def start_loop_poll(self):  # Connect to Start-button clicked()
        self.stop_loop_poll()  # Stop any existing timer
        self._generator_poll = self.read_qbpm_loop()  # Start the loop
        self._timerId_poll = self.startTimer(0)   # This is the idle timer
        self.rbtn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaPause))

    def stop_loop_poll(self):  # Connect to Stop-button clicked()
        if self._timerId_poll is not None:
            self.killTimer(self._timerId_poll)
        self._generator_poll = None
        self._timerId_poll = None
        self.rbtn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))
        self.heartbeat = time.time()

    def toggle_feedback(self):
        self.feedback = not self.feedback
        self.start_loop_feedback() if self.feedback else self.stop_loop_feedback()

    def set_feedback(self):
        counter = 0
        while True:
            interval = 20
            if self.qbpm.log_arrays['avgcurr_log'][-1] < self.feedback_threshold:
                print('intensity too low.')
                self.stop_loop_feedback()
            jitter = self.qbpm.log_arrays['posz_mvavg_log'][-int(numpy.floor(interval/2)):].std()  # calculate jitter based on last 10 log values
            bandwidth = 10 * jitter
            current_pos = self.qbpm.log_arrays['posz_mvavg_log'][-1]
            target = self.qbpm.posz_target
            corr_factor = 0.05
            if current_pos < (target + bandwidth):
                corr_angle = -(abs(current_pos - target) * corr_factor)/self.qbpm.distance
                if counter == interval:
                    print('Moving pitch down: {}'.format(corr_angle))
                    dcm_curr_pitchpos = self.dcm_pitch_tserver.Position
                    dcm_target_pitchpos = dcm_curr_pitchpos + corr_angle
                    self.dcm_pitch_tserver.write_attribute('Position', dcm_target_pitchpos)
                    counter = 0
            if current_pos > (target - bandwidth):
                corr_angle = (abs(current_pos - target) * corr_factor)/self.qbpm.distance
                if counter == interval:
                    print('Moving pitch up: {}'.format(corr_angle))
                    dcm_curr_pitchpos = self.dcm_pitch_tserver.Position
                    dcm_target_pitchpos = dcm_curr_pitchpos + corr_angle
                    self.dcm_pitch_tserver.write_attribute('Position', dcm_target_pitchpos)
                    counter = 0
            counter = 0 if counter == interval else counter + 1
            yield

    def start_loop_feedback(self):  # Connect to Start-button clicked()
        self.stop_loop_feedback()  # Stop any existing timer
        self._generator_feedback = self.set_feedback()  # Start the loop
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

    def stop_loop_feedback(self):  # Connect to Stop-button clicked()
        if self._timerId_feedback is not None:
            self.killTimer(self._timerId_feedback)
        self._generator_feedback = None
        self._timerId_feedback = None
        self.fbtn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))
        self.qbpm.feedback_on = False

    def timerEvent(self, event):
        # This is called every time the GUI is idle.
        if self.check_pulse():
            if self._generator_poll is None:
                if self._generator_feedback is not None:
                    print('timer.')
                    self.stop_loop_feedback()
                return
            try:
                next(self._generator_poll)  # Run the next iteration
                if self._generator_feedback is None:
                    return
                try:
                    next(self._generator_feedback)
                except:
                    print('generator feedback exception')
                    self.stop_loop_feedback()
            except StopIteration:
                print('generator poll exception')
                self.stop_loop_feedback()  # Iteration has finshed, kill the timer
                self.stop_loop_poll()  # Iteration has finshed, kill the timer

    def check_pulse(self):
        timedelta = time.time() - self.heartbeat
        update_delay = 1/self.qbpm.frequency
        time_to_update = False
        if timedelta > update_delay:
            time_to_update = True
            self.heartbeat = time.time()
        return time_to_update

    def change_backlog(self):
        if not self.lltext.text():
            return
        backlog = int(self.lltext.text())
        self.qbpm.change_backlog(backlog)
        self.lltext.setText(str(self.qbpm.backlog))

    def change_frequency(self):
        if not self.ftext.text():
            return
        frequency = float(self.ftext.text())
        self.qbpm.change_frequency(frequency)
        self.ftext.setText(str(self.qbpm.frequency))



class qbpm():
    def __init__(self, address, distance):
        self.tserver = tango.DeviceProxy(address)
        self.distance = distance
        self.petra = tango.DeviceProxy('hzgpp05vme1:10000/PETRA/GLOBALS/keyword')
        self.frequency = 5  # in Hz
        self.backlog = 120  # in s
        self.log_length = self.calc_log_length(self.backlog, self.frequency)
        self.log_names = {'log_vals': ['posx_log', 'posz_log', 'avgcurr_log', 'petracurrent_log'],
                          'log_mvavg': ['posx_mvavg_log', 'posz_mvavg_log', 'avgcurr_mvavg_log'],
                          'log_target': ['posx_target_log', 'posz_target_log', 'avgcurr_target_log'],
                          }
        self.log_xarr = numpy.zeros(self.log_length)
        self.adept_log_xarr()
        self.reset_logs()  # initialize log_arrays with appropriate log_length
        self.box_length = 40
        self.posx_target = 0
        self.posz_target = 0
        self.avgcurr_target = 0
        self.feedback_on = False

    def read_qbpm(self):
        # roll all log arrays
        for key, names in self.log_names.items():
            for name in names:
                self.log_arrays[name][:] = numpy.roll(self.log_arrays[name], -1)
        self.log_xarr[:] = numpy.roll(self.log_xarr, -1)
        # query qbpm and petra current, append to log array
        try:
            bc = self.petra.BeamCurrent
        except tango.DevFailed:
            bc = None
        try:
            pac = self.tserver.read_attribute('PosAndAvgCurr').value
        except tango.DevFailed:
            pac = numpy.array([None,None,None])
        server_query = numpy.append(pac, bc)
        for n, key in enumerate(self.log_names['log_vals']):
            self.log_arrays[key][-1] = server_query[n]
        # calculate moving average and append to log array
        for n, key in enumerate(self.log_names['log_mvavg']):
            mvavg = self.log_arrays[self.log_names['log_vals'][n]][-self.box_length:].mean()
            self.log_arrays[key][-1] = mvavg
        targets = [self.posx_target,  self.posz_target, self.avgcurr_target]
        for n, key in enumerate(self.log_names['log_target']):
            if self.feedback_on:
                self.log_arrays[key][-1] = targets[n]
            else:
                self.log_arrays[key][-1] = self.log_arrays[self.log_names['log_mvavg'][n]][-1]
        # finally append unix timestamp to log_xarr
        self.log_xarr[-1] = self.timestamp()
        print(self.log_xarr[-1] - self.log_xarr[0])

    def change_log_length(self, log_length):
        len_diff = abs(self.log_length - log_length)
        if log_length > self.log_length:
            for key, names in self.log_names.items():
                for name in names:
                    tmparr = numpy.full(log_length, self.log_arrays[name][0])
                    tmparr[-self.log_arrays[name].size:] = self.log_arrays[name]
                    self.log_arrays[name] = tmparr
            tmparr = numpy.resize(self.log_xarr, log_length)
            self.log_xarr = tmparr
            self.adept_log_xarr()
        else:
            for key, names in self.log_names.items():
                for name in names:
                    self.log_arrays[name][:] = numpy.roll(self.log_arrays[name], -len_diff)
                    tmparr = numpy.zeros(log_length)
                    tmparr[:] = self.log_arrays[name][-log_length:]
                    self.log_arrays[name] = tmparr
            tmparr = numpy.resize(self.log_xarr, log_length)
            self.log_xarr = tmparr
            self.adept_log_xarr()
        self.log_length = log_length

    def adept_log_xarr(self):
        len = self.log_xarr.size
        t0 = self.timestamp() - self.backlog
        t1 = self.timestamp()
        self.log_xarr = numpy.linspace(t0, t1, len)

    def calc_log_length(self, backlog, frequency):
        return int(numpy.ceil(backlog * frequency))

    def change_backlog(self, backlog):
        min_backlog = int(numpy.ceil(self.box_length / self.frequency))
        if backlog < min_backlog:
            backlog = min_backlog
        log_length = self.calc_log_length(backlog, self.frequency)
        self.backlog = backlog
        self.change_log_length(log_length)

    def change_frequency(self, frequency):
        self.frequency = frequency
        self.change_backlog(self.backlog)


    def reset_logs(self):
        bc = self.petra.BeamCurrent
        pac = self.tserver.read_attribute('PosAndAvgCurr').value
        server_query = numpy.append(pac, bc)
        self.log_arrays = {}
        set_vals = {}
        for key, names in self.log_names.items():
            for n, name in enumerate(names):
                set_vals[name] = server_query[n]
        for key, names in self.log_names.items():
            for name in names:
                self.log_arrays[name] = numpy.full(self.log_length, set_vals[name])
        self.adept_log_xarr()

    def timestamp(self):
        return time.time()


class TimeAxisItem(pg.AxisItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setLabel(text='Time', units=None)
        self.enableAutoSIPrefix(False)

    def tickStrings(self, values, scale, spacing):
        return [datetime.datetime.fromtimestamp(value).strftime("%H:%M:%S") for value in values]


def main():
    qbpm1 = 'hzgpp05vme0:10000/p05/i404/exp.01'
    qbpm2 = 'hzgpp05vme0:10000/p05/i404/exp.02'
    app = QtGui.QApplication(sys.argv)
    qbpm_mon = QbpmMonitor(qbpm2, 7)
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
