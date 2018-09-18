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


class QbpmMonitor(QtGui.QWidget):
    def __init__(self, address, distance):
        super(QbpmMonitor, self).__init__()
        self.posx_target = 0
        self.posz_target = 0
        self.avgcurr_target = 0
        self.qbpm = qbpm(address, distance)
        self.initUI()
        self.frequency = 5    # in Hz
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


    def initUI(self):
        ## Create some widgets to be placed inside
        qbtn = QtGui.QPushButton('Quit', self)
        qbtn.clicked.connect(QtCore.QCoreApplication.instance().quit)
        qbtn.resize(qbtn.sizeHint())

        reset_btn = QtGui.QPushButton('Reset', self)
        reset_btn.clicked.connect(self.reset_logs)
        reset_btn.resize(qbtn.sizeHint())

        self.rbtn = QtGui.QPushButton('Poll',self)
        self.rbtn.clicked.connect(self.toggle_polling)
        self.rbtn.resize(qbtn.sizeHint())
        self.rbtn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))

        self.fbtn = QtGui.QPushButton('Feedback',self)
        self.fbtn.clicked.connect(self.toggle_feedback)
        self.fbtn.resize(qbtn.sizeHint())
        self.fbtn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))

        self.text = QtGui.QLineEdit()
        self.text.setValidator(QtGui.QIntValidator())
        self.text.setMaxLength(6)
        self.text.returnPressed.connect(self.change_params)
#        self.listw = QtGui.QListWidget()
        r, g, w = [255, 0, 0], [0, 255, 0], [255, 255, 255]
        self.curves = {}
        log_pen = pg.mkPen('w', width=2, style=QtCore.Qt.SolidLine)
        avg_pen = pg.mkPen('r', width=3, style=QtCore.Qt.SolidLine)
        target_pen = pg.mkPen('g', width=3, style=QtCore.Qt.DashLine)
        petra_pen = pg.mkPen('w', width=3, style=QtCore.Qt.SolidLine)
        pens = [log_pen, avg_pen, target_pen]
        log_avgcurr = {'avgcurr_log': w, 'avgcurr_mvavg_log': r, 'avgcurr_target_log': g}
        self.plot_avgcurr = pg.PlotWidget(title='avg. current')
        for n, (key, color) in enumerate(log_avgcurr.items()):
            self.curves[key] = self.plot_avgcurr.plot(self.qbpm.log_arrays[key], pen=pens[n])
        log_posx = {'posx_log': w, 'posx_mvavg_log': r, 'posx_target_log': g}
        self.plot_posx = pg.PlotWidget(title='x-position')
        for n, (key, color) in enumerate(log_posx.items()):
            self.curves[key] = self.plot_posx.plot(self.qbpm.log_arrays[key], pen=pens[n])
        log_posz = {'posz_log': w, 'posz_mvavg_log': r, 'posz_target_log': g}
        self.plot_posz = pg.PlotWidget(title='z-position')
        for n, (key, color) in enumerate(log_posz.items()):
            self.curves[key] = self.plot_posz.plot(self.qbpm.log_arrays[key], pen=pens[n])

        self.plot_petracurrent = pg.PlotWidget(title='PETRA beam current')
        self.curves['petracurrent_log'] = self.plot_petracurrent.plot(self.qbpm.log_arrays['petracurrent_log'], pen=petra_pen)
        #Create a grid layout to manage the widgets size and position
        layout = QtGui.QGridLayout()
        self.setLayout(layout)

        ## Add widgets to the layout in their proper positions
        layout.addWidget(self.rbtn, 0, 0)   # button goes in lower-left
        layout.addWidget(self.fbtn, 1, 0)   # button goes in lower-left
        layout.addWidget(reset_btn, 2, 0)   # button goes in lower-left
        layout.addWidget(self.text, 3, 0)   # text edit goes in middle-left
        layout.addWidget(qbtn, 9, 0)   # button goes in lower-left
#        layout.addWidget(self.listw, 1, 0)  # list widget goes in bottom-left
        layout.addWidget(self.plot_avgcurr, 0, 1, 5, 1)  # plot goes on right side, spanning 3 rows
        layout.addWidget(self.plot_petracurrent, 0, 2, 5, 1)  # plot goes on right side, spanning 3 rows
        layout.addWidget(self.plot_posx, 5, 1, 5, 1)  # plot goes on right side, spanning 3 rows
        layout.addWidget(self.plot_posz, 5, 2, 5, 1)  # plot goes on right side, spanning 3 rows

        ## Display the widget as a new window
        self.show()

    def plot_update(self):
        for key, names in self.qbpm.log_names.items():
            for name in names:
                self.curves[name].setData(self.qbpm.log_arrays[name])

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
            time.sleep(1/self.frequency)
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

    def change_params(self):
        log_length = int(self.text.text())
        if log_length < self.qbpm.box_length:
            log_length = self.qbpm.box_length
        self.qbpm.change_log_length(log_length)

class qbpm():
    def __init__(self, address, distance):
        self.tserver = tango.DeviceProxy(address)
        self.distance = distance
        self.petra = tango.DeviceProxy('hzgpp05vme1:10000/PETRA/GLOBALS/keyword')
        self.log_length = 40
        self.log_names = {'log_vals': ['posx_log', 'posz_log', 'avgcurr_log', 'petracurrent_log'],
                          'log_mvavg': ['posx_mvavg_log', 'posz_mvavg_log', 'avgcurr_mvavg_log'],
                          'log_target': ['posx_target_log', 'posz_target_log', 'avgcurr_target_log']}
        self.reset_logs()
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

    def change_log_length(self, log_length):
        len_diff = abs(self.log_length - log_length)
        if log_length > self.log_length:
            for key, names in self.log_names.items():
                for name in names:
                    self.log_arrays[name].resize(log_length)
                    self.log_arrays[name][:] = numpy.roll(self.log_arrays[name], len_diff)
        else:
            for key, names in self.log_names.items():
                for name in names:
                    self.log_arrays[name][:] = numpy.roll(self.log_arrays[name], -len_diff)
                    self.log_arrays[name].resize(log_length)
        self.log_length = log_length

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


def main():
    qbpm1 = 'hzgpp05vme0:10000/p05/i404/exp.01'
    qbpm2 = 'hzgpp05vme0:10000/p05/i404/exp.02'
    app = QtGui.QApplication(sys.argv)
    qbpm_mon = QbpmMonitor(qbpm2, 7)
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
