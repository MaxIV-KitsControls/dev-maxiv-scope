#!/usr/bin/env python
# -*- coding:utf-8 -*-

##############################################################################
## license :
##============================================================================
##
## File :        RohdeSchwarzRTO.py
##============================================================================
##############################################################################

"""Standard Commands for Programmable Instruments (SCPI) DeviceServer """

__all__ = ["RohdeSchwarzRTO", "RohdeSchwarzRTOClass", "main"]

__docformat__ = 'restructuredtext'

import PyTango
import sys
from threading import Thread, Lock, Event
import socket
import time
import traceback
import numpy,struct,copy
from types import StringType
from rohdeschwarzrtolib import RohdeSchwarzRTOConnection
#from monitor import Monitor

##############################################################################
## Device States Description
##
## INIT :      Initialization stage.
## STANDBY :   No connection with the instrument, back to local control
## ON :        Connection stablished with the instrument, not running
## RUNNING :   Connection stablished and active monitoring.
## FAULT :     Communication error with the instrument.
##
##############################################################################

class RohdeSchwarzRTO(PyTango.Device_4Impl):

    _instrument = None
    _acquiring = Event()

    def _acquisition_loop(self):
        self._instrument.scope.clear()
        self._instrument.scope.write("STOP")
        self._instrument.scope.write(":TRIGger:MODe NORMal")
        i = 0
        t0 = time.time()
        self._acquiring.set()
        while self._acquiring.isSet():
            waveforms = self._instrument.acquire_single()
            print len(waveforms[-1])
            self.attr_WaveformDataCh1_read = waveforms[0]
            self.attr_WaveformDataCh2_read = waveforms[1]
            self.attr_WaveformDataCh3_read = waveforms[2]
            self.attr_WaveformDataCh4_read = waveforms[3]

            self.push_change_event("WaveformDataCh1", self.attr_WaveformDataCh1_read)
            self.push_change_event("WaveformDataCh2", self.attr_WaveformDataCh2_read)
            self.push_change_event("WaveformDataCh3", self.attr_WaveformDataCh3_read)
            self.push_change_event("WaveformDataCh4", self.attr_WaveformDataCh4_read)

    def change_state(self,newstate):
        self.debug_stream("In %s.change_state(%s)"%(self.get_name(),str(newstate)))
        if newstate != self.get_state():
            self.set_state(newstate)

    def connectInstrument(self):
        self.debug_stream("In connectInstrument")
        self._idn = "unknown"

        if not self._instrument:
            self._instrument =  RohdeSchwarzRTOConnection(self.Instrument)
            try:
                self._instrument.connect()
                self._idn = self._instrument.getIDN()
                #Good to catch timeout specifically
            except Exception, e:
                self.error_stream("In %s.connectInstrument() Cannot connect due to: %s"%(self.get_name(),e))
                traceback.print_exc()
                self.change_state(PyTango.DevState.FAULT)
                self.set_status("Could not connect to hardware. Check connection and do INIT.")
                print "Could not connect to hardware. Check connection and do INIT."
                self._instrument = None
                return False
            else:
                self.info_stream("In %s.connectInstrument() Connected to the instrument "\
                                 "and identified as: %s"%(self.get_name(),repr(self._idn)))
                self.change_state(PyTango.DevState.ON)
                return True

    #        def startMonitoring(self):
    #            #start a thread to check trigger
    #            print "START MON"
    #            self.monitorThread.start()

    #        def endMonitoring(self):
    #            #end thread to check trigger
    #            print "STOP MON"
    #            self.monitor.terminate()
    #            self.monitorThread.join()

#------------------------------------------------------------------
#    Device constructor
#------------------------------------------------------------------
    def __init__(self,cl, name):
        PyTango.Device_4Impl.__init__(self,cl,name)
        self.debug_stream("In " + self.get_name() + ".__init__()")
        #self.set_change_event('SpecialWaveform', True)
        RohdeSchwarzRTO.init_device(self)
        time.sleep(1.0)

        self.set_change_event('WaveformDataCh1', True)
        self.set_change_event('WaveformDataCh2', True)
        self.set_change_event('WaveformDataCh3', True)
        self.set_change_event('WaveformDataCh4', True)

#------------------------------------------------------------------
#    Device destructor
#------------------------------------------------------------------
    def delete_device(self):
        self.Standby()
        self.debug_stream("In " + self.get_name() + ".delete_device()")

#------------------------------------------------------------------
#    Device initialization
#------------------------------------------------------------------
    def init_device(self):
        self.debug_stream("In " + self.get_name() + ".init_device()")

        #put in intialise state
        self.change_state(PyTango.DevState.INIT)
        #get properties from tango DB - notably, address of hw
        self.get_device_properties(self.get_device_class())

        #common attributes
        self.attr_IDN_read = ''
        self.attr_AcquireAvailable_read = 0

        #measurment configuration
        self.attr_Measurement1_read = 'OFF'
        self.attr_Measurement2_read = 'OFF'
        self.attr_Measurement3_read = 'OFF'
        self.attr_Measurement4_read = 'OFF'
        self.attr_Measurement5_read = 'OFF'
        self.attr_Measurement6_read = 'OFF'
        self.attr_Measurement7_read = 'OFF'
        self.attr_Measurement8_read = 'OFF'

        self._measurement_wait = 1  # time to block measurement result reading after
                                    # changing the measurement type (prevents hang)
        self._measurement1_changed = time.time()
        #
        #
        self.attr_MeasurementGateOnOff_read = False
        self.attr_MeasurementGateStart_read = 0
        self.attr_MeasurementGateStop_read = 0
        self.attr_MeasurementGateOnOff_write = False
        self.attr_MeasurementGateStart_write = 0
        self.attr_MeasurementGateStop_write = 0

        #Per channel attributes
        self.attr_WaveformSumCh1_read = 0
        #
        self.attr_WaveformSumCh2_read = 0
        #
        self.attr_WaveformSumCh3_read = 0
        #
        self.attr_WaveformSumCh4_read = 0

        #---- once initialized, begin the process to connect with the instrument
        #PJB push trigger count
        #self.set_change_event("AcquireAvailable", True)
        #self._instrument = None
        if not self.connectInstrument():
            return

        #once connected check if already running or not.
        tango_status, status_str = self._instrument.getOperCond()
        self.change_state(tango_status)

        #switch to normal, external trigger mode by default
        #fix for site: don't assume anything!
        #self._instrument.setTriggerSource(1, "EXT")

        #switch to binary readout mode
        self._instrument.SetBinaryReadout()

        #check which channels are on
        self._active_channels = self._instrument.getChanStateAll()
        print "active channels",  self._active_channels

        #fast readout
        self._instrument.SetFastReadout()
        self._instrument.SetDisplayOff()

        #pjb xxx monitor thread
        #self.mymonitor = Monitor()
        #self.event_thread = Thread(target=self.mymonitor.run,args=(100,self._instrument))

        # Stored data needed for generating the time axis scale
        # Get current settings but also insist on reasonably small record length
        #
        #set to fixed record length first
        self._instrument.setFixedRecordLength()
        self._record_length = self._instrument.getRecordLength()
        if self._record_length > 10000:
            self._record_length = 10000
            self._instrument.setRecordLength(self._record_length)
        #
        self._hscale =  self._instrument.getHScale()
        #
        #possibly we only read out 1 in n of points in the record (interpolate)
        #print "mode is ", self._instrument.GetWaveformMode(1)
        #"The R&S RTO uses decimation, if waveform "Sample rate" is less than the "ADC sample rate""
        #Two options - may decimate the wf and read only 1 in n samples
        #May interpolate and read 1 in n and fill the gaps
        #In first case wf will not be full record length, in second case it will be expanded to fill
        #Can just check the size and fill to full length_
        #print "mode is ", self._instrument.GetAcquireMode()
        #print "adc rate is ", self._instrument.GetADCSampleRate()
        #print "sam rate is ", self._instrument.GetSampleRate()
        self._recalc_time_scale()

        #initialise waveforms with required length
        self.attr_WaveformDataCh1_read = [0.0]*self._record_length
        self.attr_WaveformDataCh2_read = [0.0]*self._record_length
        self.attr_WaveformDataCh3_read = [0.0]*self._record_length
        self.attr_WaveformDataCh4_read = [0.0]*self._record_length


    def _recalc_time_scale(self):
        self._time_scale = numpy.linspace(-self._hscale/2, self._hscale/2, self._record_length)

#------------------------------------------------------------------
#    Always excuted hook method
#------------------------------------------------------------------
    def always_executed_hook(self):

        self.debug_stream("In " + self.get_name() + ".always_excuted_hook() with status ", self.get_state())

        #if we put it in standby, do nothing
        if self.get_state() in [PyTango.DevState.STANDBY]:
            return

        #if its in fault do nothing - can only be recovered by an INIT
        if self.get_state() in [PyTango.DevState.FAULT]:
            return

        #check status, assuming connection OK, and hence also state of connection
        try:
            tango_status, status_str = self._instrument.getOperCond()
            self.set_status(status_str)
            self.set_state(tango_status)
        except socket.timeout:
            self.error_stream("In always_executed_hook() Lost connection due to timeout")
            self.set_status("Lost connection with instrument (timeout). Check and do INIT")
            self.set_state(PyTango.DevState.FAULT)
            self._instrument = None #PJB needed to prevent client trying to read other attributes
        except Exception,e:
            self.error_stream("In %s.always_executed_hook() Lost connection due to: %s"%(self.get_name(),e))
            self.set_status("Lost connection with instrument. Check and do INIT")
            self.set_state(PyTango.DevState.FAULT)
            self._instrument = None #PJB needed to prevent client trying to read other attributes

#==================================================================
#
#    RohdeSchwarzRTO read/write attribute methods
#
#==================================================================

#------------------------------------------------------------------
#    Read Idn attribute
#------------------------------------------------------------------
    def read_IDN(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Idn()")
        #doesn't actually read the hw each time
        attr.set_value(self._idn)

#------------------------------------------------------------------
#    Read AcquireAvailable attribute
#------------------------------------------------------------------
    def read_AcquireAvailable(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_AcquireAvailable()")
        # try:

        #     self.attr_AcquireAvailable_read = int(self._instrument.getCount())
        #     attr.set_value(self.attr_AcquireAvailable_read)

        #     #PJB self.push_change_event("AcquireAvailable", int(os))
        #     #PJB need to read wave form and get sum here, if this counter is polled
        #     #VH - should really ask for count and waveform data in same command
        #     #to ensure synchronisation! ie that wf i goes with trigger i

        #     if self.attr_AcquireAvailable_read>0:

        #         currentdata = self._instrument.getWaveformData(1)
        #         self.attr_WaveformDataCh1_read = currentdata
        #         self.attr_WaveformSumCh1_read = self._instrument.sumWaveform(currentdata)
        #         currentdata = self._instrument.getWaveformData(2)
        #         self.attr_WaveformDataCh2_read = currentdata
        #         self.attr_WaveformSumCh2_read = self._instrument.sumWaveform(currentdata)
        #         currentdata = self._instrument.getWaveformData(3)
        #         self.attr_WaveformDataCh3_read = currentdata
        #         self.attr_WaveformSumCh3_read = self._instrument.sumWaveform(currentdata)
        #         currentdata = self._instrument.getWaveformData(4)
        #         self.attr_WaveformDataCh4_read = currentdata
        #         self.attr_WaveformSumCh4_read = self._instrument.sumWaveform(currentdata)

        #    #   currentdata = self._instrument.getWaveformData(2)
        #    #  self.myWaveformDataCh2 = currentdata
        #    #  self.myWaveformSumCh2 = self._instrument.sumWaveform(currentdata)
        #    #  currentdata = self._instrument.getWaveformData(3)
        #    #  self.myWaveformDataCh3 = currentdata
        #    #  self.myWaveformSumCh3 = self._instrument.sumWaveform(currentdata)
        #    #  currentdata = self._instrument.getWaveformData(4)
        #    #  self.myWaveformDataCh4 = currentdata
        #    #  self.myWaveformSumCh4 = self._instrument.sumWaveform(currentdata)
        # except Exception,e:
        #     self.error_stream("Cannot read AcquireAvailable or WaveformData due to: %s"%e)
        #     attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
        #     return
    def is_AcquireAvailable_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False
#------------------------------------------------------------------
#    Read FixedRecordLength attribute
#------------------------------------------------------------------
#    def read_FixedRecordLength(self, attr):
#        self.debug_stream("In " + self.get_name() + ".read_FixedRecordLength()")
#        try:
#            os = self._instrument.getFixedRecordLength()
#            attr.set_value(os)
#        except Exception,e:
#            self.error_stream("Cannot read FixedRecordLength due to: %s"%e)
#            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
#            return
#    def is_FixedRecordLength_allowed(self, req_type):
#        if self._instrument is not None:
#            return True
#        else:
#            return False
#------------------------------------------------------------------
#    Read RecordLength attribute
#------------------------------------------------------------------
    def read_RecordLength(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_RecordLength()")
        try:
            os = self._instrument.getRecordLength()
            attr.set_value(os)
            attr.set_write_value(os)
        except Exception,e:
            self.error_stream("Cannot read RecordLength due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
    def is_RecordLength_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False
#------------------------------------------------------------------
#    Write RecordLength attribute
#    This also fixes the record length, i.e. so that resolution changes
#------------------------------------------------------------------
    def write_RecordLength(self, attr):
        #now set value
        data = attr.get_write_value()
        self._instrument.setRecordLength(data)
        self._record_length = data
        self._recalc_time_scale()
        self.attr_WaveformDataCh1_read = [0.0]*self._record_length
        self.attr_WaveformDataCh2_read = [0.0]*self._record_length
        self.attr_WaveformDataCh3_read = [0.0]*self._record_length
        self.attr_WaveformDataCh4_read = [0.0]*self._record_length

    # def read_SpecialWaveform(self, attr):
    #     if self._special_waveform is not None:
    #         attr.set_value(self._special_waveform)

    # def is_SpecialWaveform_allowed(self, req_type):
    #     return True

#------------------------------------------------------------------
#    Read WaveformSumCh1 attribute
#------------------------------------------------------------------
    def read_WaveformSumCh1(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_WaveformSumCh1()")
        #not read from hw here
        attr.set_value(self.attr_WaveformSumCh1_read)

#------------------------------------------------------------------
#    Read WaveformSumCh2 attribute
#------------------------------------------------------------------
    def read_WaveformSumCh2(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_WaveformSumCh2()")
        #not read from hw here
        attr.set_value(self.attr_WaveformSumCh2_read)
#------------------------------------------------------------------
#    Read WaveformSumCh3 attribute
#------------------------------------------------------------------
    def read_WaveformSumCh3(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_WaveformSumCh3()")
        #not read from hw here
        attr.set_value(self.attr_WaveformSumCh3_read)
#------------------------------------------------------------------
#    Read WaveformSumCh4 attribute
#------------------------------------------------------------------
    def read_WaveformSumCh4(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_WaveformSumCh4()")
        #not read from hw here
        attr.set_value(self.attr_WaveformSumCh4_read)

#------------------------------------------------------------------
#    Read TimeScale attribute
#------------------------------------------------------------------
    def read_TimeScale(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_TimeScale()")
        # TimeScale is a "virtual" attribute that is calculated from
        # the size of the time window (HScale) and the number of data
        # points (RecordLength).
        attr.set_value(self._time_scale)

    def is_TimeScale_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False

#------------------------------------------------------------------
#    Read WaveformDataCh1 attribute
#------------------------------------------------------------------
# DO NOT READ HW HERE IF ALREADY READ IN THE ACQUIRE AVAILABLE ATTRIBUTE READING
# SHOULD WE USE READ ATTRIB HW INSTEAD?
    def read_WaveformDataCh1(self, attr):

        self.debug_stream("In " + self.get_name() + ".read_WaveformDataCh1()")

        try:
            # if self.attr_AcquireAvailable_read>0:
            #     print "dsadsad"
            #     self.attr_WaveformDataCh1_read = self._instrument.getWaveformData(1)
            attr.set_value(self.attr_WaveformDataCh1_read)
            self.attr_WaveformSumCh1_read = self._instrument.sumWaveform(self.attr_WaveformDataCh1_read)
        except Exception,e:
            self.error_stream("Cannot read WaveformDataCh1 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return

    def is_WaveformDataCh1_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False
#------------------------------------------------------------------
#    Read WaveformDataCh2 attribute
#------------------------------------------------------------------
    def read_WaveformDataCh2(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_WaveformDataCh2()")

        try:
            # if self.attr_AcquireAvailable_read>0:
            #    self.attr_WaveformDataCh2_read = self._instrument.getWaveformData(2)
            attr.set_value(self.attr_WaveformDataCh2_read)
            self.attr_WaveformSumCh2_read = self._instrument.sumWaveform(self.attr_WaveformDataCh2_read)
        except Exception,e:
            self.error_stream("Cannot read WaveformDataCh2 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return

    def is_WaveformDataCh2_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False
#------------------------------------------------------------------
#    Read WaveformDataCh3 attribute
#------------------------------------------------------------------
    def read_WaveformDataCh3(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_WaveformDataCh3()")

        try:
            # if self.attr_AcquireAvailable_read>0:
            #    self.attr_WaveformDataCh3_read = self._instrument.getWaveformData(3)
            attr.set_value(self.attr_WaveformDataCh3_read)
            self.attr_WaveformSumCh3_read = self._instrument.sumWaveform(self.attr_WaveformDataCh3_read)
        except Exception,e:
            self.error_stream("Cannot read WaveformDataCh3 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return

    def is_WaveformDataCh3_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False
#------------------------------------------------------------------
#    Read WaveformDataCh4 attribute
#------------------------------------------------------------------
    def read_WaveformDataCh4(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_WaveformDataCh4()")

        try:
            # if self.attr_AcquireAvailable_read>0:
            #    self.attr_WaveformDataCh4_read = self._instrument.getWaveformData(4)
            attr.set_value(self.attr_WaveformDataCh4_read)
            self.attr_WaveformSumCh4_read = self._instrument.sumWaveform(self.attr_WaveformDataCh4_read)
        except Exception,e:
            self.error_stream("Cannot read WaveformDataCh4 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return


    def is_WaveformDataCh4_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False

#------------------------------------------------------------------
#    Read CouplingCh1 attribute
#------------------------------------------------------------------
    def read_CouplingCh1(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_CouplingCh1()")
        try:
            os = self._instrument.getCoupling(1)
            attr.set_value(os)
            attr.set_write_value(os)
        except Exception,e:
            self.error_stream("Cannot read CouplingCh1 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Read CouplingCh2 attribute
#------------------------------------------------------------------
    def read_CouplingCh2(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_CouplingCh2()")
        try:
            os = self._instrument.getCoupling(2)
            attr.set_value(os)
            attr.set_write_value(os)
        except Exception,e:
            self.error_stream("Cannot read CouplingCh2 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Read CouplingCh3 attribute
#------------------------------------------------------------------
    def read_CouplingCh3(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_CouplingCh3()")
        try:
            os = self._instrument.getCoupling(3)
            attr.set_value(os)
            attr.set_write_value(os)
        except Exception,e:
            self.error_stream("Cannot read CouplingCh3 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Read CouplingCh4 attribute
#------------------------------------------------------------------
    def read_CouplingCh4(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_CouplingCh4()")
        try:
            os = self._instrument.getCoupling(4)
            attr.set_value(os)
            attr.set_write_value(os)
        except Exception,e:
            self.error_stream("Cannot read CouplingCh4 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write CouplingCh1 attribute
#------------------------------------------------------------------
    def write_CouplingCh1(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setCoupling(1,data)
        except Exception,e:
            self.error_stream("Cannot configure input coupling due to: %s"%e)
    def is_CouplingCh1_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False
#------------------------------------------------------------------
#    Write CouplingCh2 attribute
#------------------------------------------------------------------
    def write_CouplingCh2(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setCoupling(2,data)
        except Exception,e:
            self.error_stream("Cannot configure input coupling due to: %s"%e)
    def is_CouplingCh2_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False
#------------------------------------------------------------------
#    Write CouplingCh3 attribute
#------------------------------------------------------------------
    def write_CouplingCh3(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setCoupling(3,data)
        except Exception,e:
            self.error_stream("Cannot configure input coupling due to: %s"%e)
    def is_CouplingCh3_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False
#------------------------------------------------------------------
#    Write CouplingCh4 attribute
#------------------------------------------------------------------
    def write_CouplingCh4(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setCoupling(4,data)
        except Exception,e:
            self.error_stream("Cannot configure input coupling due to: %s"%e)
    def is_CouplingCh4_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False


#------------------------------------------------------------------
#    Read OffsetCh1 attribute
#------------------------------------------------------------------
    def read_OffsetCh1(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_OffsetCh1()")
        try:
            os = self._instrument.getOffset(1)
            attr.set_value(os)
            attr.set_write_value(os)
        except Exception,e:
            self.error_stream("Cannot read OffsetCh1 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return

#------------------------------------------------------------------
#    Read OffsetCh2 attribute
#------------------------------------------------------------------
    def read_OffsetCh2(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_OffsetCh2()")
        try:
            os = self._instrument.getOffset(2)
            attr.set_value(os)
            attr.set_write_value(os)
        except Exception,e:
            self.error_stream("Cannot read OffsetCh1 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Read OffsetCh3 attribute
#------------------------------------------------------------------
    def read_OffsetCh3(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_OffsetCh3()")
        try:
            os = self._instrument.getOffset(3)
            attr.set_value(os)
            attr.set_write_value(os)
        except Exception,e:
            self.error_stream("Cannot read OffsetCh3 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Read OffsetCh4 attribute
#------------------------------------------------------------------
    def read_OffsetCh4(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_OffsetCh4()")
        try:
            os = self._instrument.getOffset(4)
            attr.set_value(os)
            attr.set_write_value(os)
        except Exception,e:
            self.error_stream("Cannot read OffsetCh4 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write OffsetCh1 attribute
#------------------------------------------------------------------
    def write_OffsetCh1(self, attr):
        data = attr.get_write_value()
        self._instrument.setOffset(1,data)
    def is_OffsetCh1_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False
#------------------------------------------------------------------
#    Write OffsetCh2 attribute
#------------------------------------------------------------------
    def write_OffsetCh2(self, attr):
        data = attr.get_write_value()
        self._instrument.setOffset(2,data)
    def is_OffsetCh2_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False
#------------------------------------------------------------------
#    Write OffsetCh3 attribute
#------------------------------------------------------------------
    def write_OffsetCh3(self, attr):
        data = attr.get_write_value()
        self._instrument.setOffset(3,data)
    def is_OffsetCh3_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False
#------------------------------------------------------------------
#    Write OffsetCh4 attribute
#------------------------------------------------------------------
    def write_OffsetCh4(self, attr):
        data = attr.get_write_value()
        self._instrument.setOffset(4,data)
    def is_OffsetCh4_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False
#------------------------------------------------------------------
#    Read VScaleCh1 attribute
#------------------------------------------------------------------
    def read_VScaleCh1(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_VScaleCh1()")
        try:
            os = self._instrument.getVScale(1)
            attr.set_value(os)
            attr.set_write_value(os)
        except Exception,e:
            self.error_stream("Cannot read VScaleCh1 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Read VScaleCh2 attribute
#------------------------------------------------------------------
    def read_VScaleCh2(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_VScaleCh2()")
        try:
            os = self._instrument.getVScale(2)
            attr.set_value(os)
            attr.set_write_value(os)
        except Exception,e:
            self.error_stream("Cannot read VScaleCh2 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Read VScaleCh3 attribute
#------------------------------------------------------------------
    def read_VScaleCh3(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_VScaleCh3()")
        try:
            os = self._instrument.getVScale(3)
            attr.set_value(os)
            attr.set_write_value(os)
        except Exception,e:
            self.error_stream("Cannot read VScaleCh3 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Read VScaleCh4 attribute
#------------------------------------------------------------------
    def read_VScaleCh4(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_VScaleCh4()")
        try:
            os = self._instrument.getVScale(4)
            attr.set_value(os)
            attr.set_write_value(os)
        except Exception,e:
            self.error_stream("Cannot read VScaleCh4 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write VScaleCh1 attribute
#------------------------------------------------------------------
    def write_VScaleCh1(self, attr):
        data = attr.get_write_value()
        self._instrument.setVScale(1,data)
    def is_VScaleCh1_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False
#------------------------------------------------------------------
#    Write VScaleCh2 attribute
#------------------------------------------------------------------
    def write_VScaleCh2(self, attr):
        data = attr.get_write_value()
        self._instrument.setVScale(2,data)
    def is_VScaleCh2_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False
#------------------------------------------------------------------
#    Write VScaleCh3 attribute
#------------------------------------------------------------------
    def write_VScaleCh3(self, attr):
        data = attr.get_write_value()
        self._instrument.setVScale(3,data)
    def is_VScaleCh3_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False
#------------------------------------------------------------------
#    Write VScaleCh4 attribute
#------------------------------------------------------------------
    def write_VScaleCh4(self, attr):
        data = attr.get_write_value()
        self._instrument.setVScale(4,data)
    def is_VScaleCh4_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False
#------------------------------------------------------------------
#    Read HScale attribute
#------------------------------------------------------------------
    def read_HScale(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_HScale()")
        try:
            os = self._instrument.getHScale()
            attr.set_value(os)
            attr.set_write_value(os)
            if os != self._hscale:
                self._hscale = os
                self._recalc_time_scale()
        except:
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)

#------------------------------------------------------------------
#    Write HScale attribute
#------------------------------------------------------------------
    def write_HScale(self, attr):
        data = attr.get_write_value()
        self._instrument.setHScale(data)
        self._hscale = data
        self._recalc_time_scale()

    def is_HScale_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False

#------------------------------------------------------------------
#    Read Trig1Source attribute
#------------------------------------------------------------------
    def read_Trig1Source(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Trig1Source()")
        try:
            os = self._instrument.getTriggerSource(1)
            attr.set_value(os)
            attr.set_write_value(os)
        except:
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)

#------------------------------------------------------------------
#    Write Trig1Source attribute
#------------------------------------------------------------------
    def write_Trig1Source(self, attr):
        data = attr.get_write_value()
        self._instrument.setTriggerSource(1, data)
    def is_Trig1Source_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False


#------------------------------------------------------------------
#    Read Trig1Mode attribute
#------------------------------------------------------------------
    def read_Trig1Mode(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Trig1Mode()")
        try:
            os = self._instrument.getTriggerMode(1)
            attr.set_value(os)
            attr.set_write_value(os)
        except:
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)

#------------------------------------------------------------------
#    Write Trig1Mode attribute
#------------------------------------------------------------------
    def write_Trig1Mode(self, attr):
        data = attr.get_write_value()
        self._instrument.setTriggerMode(1, data)
    def is_Trig1Mode_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False


#------------------------------------------------------------------
#    Read TrigLevel attribute
#------------------------------------------------------------------
    def read_TrigLevel(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_TrigLevel()")
        try:
            os = self._instrument.getTrigLevel()
            attr.set_value(os)
            attr.set_write_value(os)
        except:
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)

#------------------------------------------------------------------
#    Write TrigLevel attribute
#------------------------------------------------------------------
    def write_TrigLevel(self, attr):
        data = attr.get_write_value()
        self._instrument.setTrigLevel(data)
    def is_TrigLevel_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False

#------------------------------------------------------------------
#    Read StateCh1 attribute
#------------------------------------------------------------------
    def read_StateCh1(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_StateCh1()")
        try:
            attr_StateCh1_read = self._instrument.getChanState(1)
            print "here", attr_StateCh1_read
            attr.set_value(attr_StateCh1_read)
            attr.set_write_value(attr_StateCh1_read)
        except Exception,e:
            self.error_stream("Cannot read StateCh1 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write StateCh1 attribute
#------------------------------------------------------------------
    def write_StateCh1(self, attr):
        data = attr.get_write_value()
        print "setting", data
        try:
            self._instrument.setChanState(1,data)
            self._active_channels = self._instrument.getChanStateAll()
        except Exception,e:
            self.error_stream("Cannot configure StateCh1 due to: %s"%e)

    def is_StateCh1_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False

#------------------------------------------------------------------
#    Read StateCh2 attribute
#------------------------------------------------------------------
    def read_StateCh2(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_StateCh2()")
        try:
            attr_StateCh2_read = self._instrument.getChanState(2)
            attr.set_value(attr_StateCh2_read)
            attr.set_write_value(attr_StateCh2_read)
        except Exception,e:
            self.error_stream("Cannot read StateCh2 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write StateCh2 attribute
#------------------------------------------------------------------
    def write_StateCh2(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setChanState(2,data)
            self._active_channels = self._instrument.getChanStateAll()
        except Exception,e:
            self.error_stream("Cannot configure StateCh2 due to: %s"%e)

    def is_StateCh2_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False

#------------------------------------------------------------------
#    Read StateCh3 attribute
#------------------------------------------------------------------
    def read_StateCh3(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_StateCh3()")
        try:
            attr_StateCh3_read = self._instrument.getChanState(3)
            attr.set_value(attr_StateCh3_read)
            attr.set_write_value(attr_StateCh3_read)
        except Exception,e:
            self.error_stream("Cannot read StateCh3 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write StateCh3 attribute
#------------------------------------------------------------------
    def write_StateCh3(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setChanState(3,data)
            self._active_channels = self._instrument.getChanStateAll()
        except Exception,e:
            self.error_stream("Cannot configure StateCh3 due to: %s"%e)

    def is_StateCh3_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False

#------------------------------------------------------------------
#    Read StateCh4 attribute
#------------------------------------------------------------------
    def read_StateCh4(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_StateCh4()")
        try:
            attr_StateCh4_read = self._instrument.getChanState(4)
            attr.set_value(attr_StateCh4_read)
            attr.set_write_value(attr_StateCh4_read)
        except Exception,e:
            self.error_stream("Cannot read StateCh4 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write StateCh4 attribute
#------------------------------------------------------------------
    def write_StateCh4(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setChanState(4,data)
            self._active_channels = self._instrument.getChanStateAll()
        except Exception,e:
            self.error_stream("Cannot configure StateCh4 due to: %s"%e)

    def is_StateCh4_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False


#
# MEASUREMENTS
# ============
#
#------------------------------------------------------------------
#    Read Measurement1 attribute
#------------------------------------------------------------------
    def read_Measurement1(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Measurement1()")
        try:
            self.attr_Measurement1_read = self._instrument.getMeasurement(1)
            attr.set_value(self.attr_Measurement1_read)
            attr.set_write_value(self.attr_Measurement1_read)
        except Exception,e:
            self.error_stream("Cannot read Measurement1 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write Measurement1 attribute
#------------------------------------------------------------------
    def write_Measurement1(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setMeasurement(1,data)
        except Exception,e:
            self.error_stream("Cannot configure Measurement1 due to: %s"%e)
        self._measurement1_changed = time.time()

    def is_Measurement1_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False
#------------------------------------------------------------------
#    Read Measurement2 attribute
#------------------------------------------------------------------
    def read_Measurement2(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Measurement2()")
        try:
            self.attr_Measurement2_read = self._instrument.getMeasurement(2)
            attr.set_value(self.attr_Measurement2_read)
            attr.set_write_value(self.attr_Measurement2_read)
        except Exception,e:
            self.error_stream("Cannot read Measurement2 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write Measurement2 attribute
#------------------------------------------------------------------
    def write_Measurement2(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setMeasurement(2,data)
        except Exception,e:
            self.error_stream("Cannot configure Measurement2 due to: %s"%e)
    def is_Measurement2_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False
#------------------------------------------------------------------
#    Read Measurement3 attribute
#------------------------------------------------------------------
    def read_Measurement3(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Measurement3()")
        try:
            self.attr_Measurement3_read = self._instrument.getMeasurement(3)
            attr.set_value(self.attr_Measurement3_read)
            attr.set_write_value(self.attr_Measurement3_read)
        except Exception,e:
            self.error_stream("Cannot read Measurement3 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write Measurement3 attribute
#------------------------------------------------------------------
    def write_Measurement3(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setMeasurement(3,data)
        except Exception,e:
            self.error_stream("Cannot configure Measurement3 due to: %s"%e)
    def is_Measurement3_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False
#------------------------------------------------------------------
#    Read Measurement4 attribute
#------------------------------------------------------------------
    def read_Measurement4(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Measurement4()")
        try:
            self.attr_Measurement4_read = self._instrument.getMeasurement(4)
            attr.set_value(self.attr_Measurement4_read)
            attr.set_write_value(self.attr_Measurement4_read)
        except Exception,e:
            self.error_stream("Cannot read Measurement4 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write Measurement4 attribute
#------------------------------------------------------------------
    def write_Measurement4(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setMeasurement(4,data)
        except Exception,e:
            self.error_stream("Cannot configure Measurement4 due to: %s"%e)
    def is_Measurement4_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False
#------------------------------------------------------------------
#    Read Measurement5 attribute
#------------------------------------------------------------------
    def read_Measurement5(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Measurement5()")
        try:
            self.attr_Measurement5_read = self._instrument.getMeasurement(5)
            attr.set_value(self.attr_Measurement5_read)
            attr.set_write_value(self.attr_Measurement5_read)
        except Exception,e:
            self.error_stream("Cannot read Measurement5 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write Measurement5 attribute
#------------------------------------------------------------------
    def write_Measurement5(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setMeasurement(5,data)
        except Exception,e:
            self.error_stream("Cannot configure Measurement5 due to: %s"%e)
    def is_Measurement5_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False
#------------------------------------------------------------------
#    Read Measurement6 attribute
#------------------------------------------------------------------
    def read_Measurement6(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Measurement6()")
        try:
            self.attr_Measurement6_read = self._instrument.getMeasurement(6)
            attr.set_value(self.attr_Measurement6_read)
            attr.set_write_value(self.attr_Measurement6_read)
        except Exception,e:
            self.error_stream("Cannot read Measurement6 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write Measurement6 attribute
#------------------------------------------------------------------
    def write_Measurement6(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setMeasurement(6,data)
        except Exception,e:
            self.error_stream("Cannot configure Measurement6 due to: %s"%e)
    def is_Measurement6_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False
#------------------------------------------------------------------
#    Read Measurement7 attribute
#------------------------------------------------------------------
    def read_Measurement7(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Measurement7()")
        try:
            self.attr_Measurement7_read = self._instrument.getMeasurement(7)
            attr.set_value(self.attr_Measurement7_read)
            attr.set_write_value(self.attr_Measurement7_read)
        except Exception,e:
            self.error_stream("Cannot read Measurement7 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write Measurement7 attribute
#------------------------------------------------------------------
    def write_Measurement7(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setMeasurement(7,data)
        except Exception,e:
            self.error_stream("Cannot configure Measurement7 due to: %s"%e)
    def is_Measurement7_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False
#------------------------------------------------------------------
#    Read Measurement8 attribute
#------------------------------------------------------------------
    def read_Measurement8(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Measurement8()")
        try:
            self.attr_Measurement8_read = self._instrument.getMeasurement(8)
            attr.set_value(self.attr_Measurement8_read)
            attr.set_write_value(self.attr_Measurement8_read)
        except Exception,e:
            self.error_stream("Cannot read Measurement8 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write Measurement8 attribute
#------------------------------------------------------------------
    def write_Measurement8(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setMeasurement(8,data)
        except Exception,e:
            self.error_stream("Cannot configure Measurement8 due to: %s"%e)
    def is_Measurement8_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False


#------------------------------------------------------------------
#    Read Measurement1Source attribute
#------------------------------------------------------------------
    def read_Measurement1Source(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Measurement1Source()")
        try:
            self.attr_Measurement1Source_read = self._instrument.getMeasurementSource(1)
            attr.set_value(self.attr_Measurement1Source_read)
            attr.set_write_value(self.attr_Measurement1Source_read)
        except Exception,e:
            self.error_stream("Cannot read Measurement1Source due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write Measurement1Source attribute
#------------------------------------------------------------------
    def write_Measurement1Source(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setMeasurementSource(1,data)
        except Exception,e:
            self.error_stream("Cannot configure Measurement1Source due to: %s"%e)
        self._measurement1_changed = time.time()

    def is_Measurement1_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False

#------------------------------------------------------------------
#    Read Measurement2Source attribute
#------------------------------------------------------------------
    def read_Measurement2Source(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Measurement2Source()")
        try:
            self.attr_Measurement2Source_read = self._instrument.getMeasurementSource(2)
            attr.set_value(self.attr_Measurement2Source_read)
            attr.set_write_value(self.attr_Measurement2Source_read)
        except Exception,e:
            self.error_stream("Cannot read Measurement2Source due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write Measurement2Source attribute
#------------------------------------------------------------------
    def write_Measurement2Source(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setMeasurementSource(2,data)
        except Exception,e:
            self.error_stream("Cannot configure Measurement2Source due to: %s"%e)
        self._measurement2_changed = time.time()

    def is_Measurement2_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False

#------------------------------------------------------------------
#    Read Measurement3Source attribute
#------------------------------------------------------------------
    def read_Measurement3Source(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Measurement3Source()")
        try:
            self.attr_Measurement3Source_read = self._instrument.getMeasurementSource(3)
            attr.set_value(self.attr_Measurement3Source_read)
            attr.set_write_value(self.attr_Measurement3Source_read)
        except Exception,e:
            self.error_stream("Cannot read Measurement3Source due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write Measurement3Source attribute
#------------------------------------------------------------------
    def write_Measurement3Source(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setMeasurementSource(3,data)
        except Exception,e:
            self.error_stream("Cannot configure Measurement3Source due to: %s"%e)
        self._measurement3_changed = time.time()

    def is_Measurement3_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False

#------------------------------------------------------------------
#    Read Measurement4Source attribute
#------------------------------------------------------------------
    def read_Measurement4Source(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Measurement4Source()")
        try:
            self.attr_Measurement4Source_read = self._instrument.getMeasurementSource(4)
            attr.set_value(self.attr_Measurement4Source_read)
            attr.set_write_value(self.attr_Measurement4Source_read)
        except Exception,e:
            self.error_stream("Cannot read Measurement4Source due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write Measurement4Source attribute
#------------------------------------------------------------------
    def write_Measurement4Source(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setMeasurementSource(4,data)
        except Exception,e:
            self.error_stream("Cannot configure Measurement4Source due to: %s"%e)
        self._measurement4_changed = time.time()

    def is_Measurement4_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False

#------------------------------------------------------------------
#    Read Measurement5Source attribute
#------------------------------------------------------------------
    def read_Measurement5Source(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Measurement5Source()")
        try:
            self.attr_Measurement5Source_read = self._instrument.getMeasurementSource(5)
            attr.set_value(self.attr_Measurement5Source_read)
            attr.set_write_value(self.attr_Measurement5Source_read)
        except Exception,e:
            self.error_stream("Cannot read Measurement5Source due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write Measurement5Source attribute
#------------------------------------------------------------------
    def write_Measurement5Source(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setMeasurementSource(5,data)
        except Exception,e:
            self.error_stream("Cannot configure Measurement5Source due to: %s"%e)
        self._measurement5_changed = time.time()

    def is_Measurement5_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False

#------------------------------------------------------------------
#    Read Measurement6Source attribute
#------------------------------------------------------------------
    def read_Measurement6Source(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Measurement6Source()")
        try:
            self.attr_Measurement6Source_read = self._instrument.getMeasurementSource(6)
            attr.set_value(self.attr_Measurement6Source_read)
            attr.set_write_value(self.attr_Measurement6Source_read)
        except Exception,e:
            self.error_stream("Cannot read Measurement6Source due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write Measurement6Source attribute
#------------------------------------------------------------------
    def write_Measurement6Source(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setMeasurementSource(6,data)
        except Exception,e:
            self.error_stream("Cannot configure Measurement6Source due to: %s"%e)
        self._measurement6_changed = time.time()

    def is_Measurement6_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False

#------------------------------------------------------------------
#    Read Measurement7Source attribute
#------------------------------------------------------------------
    def read_Measurement7Source(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Measurement7Source()")
        try:
            self.attr_Measurement7Source_read = self._instrument.getMeasurementSource(7)
            attr.set_value(self.attr_Measurement7Source_read)
            attr.set_write_value(self.attr_Measurement7Source_read)
        except Exception,e:
            self.error_stream("Cannot read Measurement7Source due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write Measurement7Source attribute
#------------------------------------------------------------------
    def write_Measurement7Source(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setMeasurementSource(7,data)
        except Exception,e:
            self.error_stream("Cannot configure Measurement7Source due to: %s"%e)
        self._measurement7_changed = time.time()

    def is_Measurement7_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False

#------------------------------------------------------------------
#    Read Measurement8Source attribute
#------------------------------------------------------------------
    def read_Measurement8Source(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Measurement8Source()")
        try:
            self.attr_Measurement8Source_read = self._instrument.getMeasurementSource(8)
            attr.set_value(self.attr_Measurement8Source_read)
            attr.set_write_value(self.attr_Measurement8Source_read)
        except Exception,e:
            self.error_stream("Cannot read Measurement8Source due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write Measurement8Source attribute
#------------------------------------------------------------------
    def write_Measurement8Source(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setMeasurementSource(8,data)
        except Exception,e:
            self.error_stream("Cannot configure Measurement8Source due to: %s"%e)
        self._measurement8_changed = time.time()

    def is_Measurement8_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False


#------------------------------------------------------------------
#    Read Measurement1Res attribute
#------------------------------------------------------------------
    def read_Measurement1Res(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Measurement1Res()")
        try:
            os = self._instrument.getMeasurementRes(1)
            attr.set_value(os)
        except Exception,e:
            self.error_stream("Cannot read MeasurementRes1 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return

    def is_Measurement1Res_allowed(self, req_type):
        recently_changed = (self._measurement1_changed + self._measurement_wait) > time.time()
        if self._instrument is not None and (not recently_changed) and self.attr_Measurement1_read != 'OFF':
            return True
        else:
            return False
#------------------------------------------------------------------
#    Read Measurement2Res attribute
#------------------------------------------------------------------
    def read_Measurement2Res(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Measurement2Res()")
        try:
            os = self._instrument.getMeasurementRes(2)
            attr.set_value(os)
        except Exception,e:
            self.error_stream("Cannot read MeasurementRes2 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
    def is_Measurement2Res_allowed(self, req_type):
        if self._instrument is not None and self.attr_Measurement2_read != 'OFF':
            return True
        else:
            return False
#------------------------------------------------------------------
#    Read Measurement3Res attribute
#------------------------------------------------------------------
    def read_Measurement3Res(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Measurement3Res()")
        try:
            os = self._instrument.getMeasurementRes(3)
            attr.set_value(os)
        except Exception,e:
            self.error_stream("Cannot read MeasurementRes3 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
    def is_Measurement3Res_allowed(self, req_type):
        if self._instrument is not None and self.attr_Measurement3_read != 'OFF':
            return True
        else:
            return False
#------------------------------------------------------------------
#    Read Measurement4Res attribute
#------------------------------------------------------------------
    def read_Measurement4Res(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Measurement4Res()")
        try:
            os = self._instrument.getMeasurementRes(4)
            attr.set_value(os)
        except Exception,e:
            self.error_stream("Cannot read MeasurementRes4 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
    def is_Measurement4Res_allowed(self, req_type):
        if self._instrument is not None and self.attr_Measurement4_read != 'OFF':
            return True
        else:
            return False
#------------------------------------------------------------------
#    Read Measurement5Res attribute
#------------------------------------------------------------------
    def read_Measurement5Res(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Measurement5Res()")
        try:
            os = self._instrument.getMeasurementRes(5)
            attr.set_value(os)
        except Exception,e:
            self.error_stream("Cannot read MeasurementRes5 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
    def is_Measurement5Res_allowed(self, req_type):
        if self._instrument is not None and self.attr_Measurement5_read != 'OFF':
            return True
        else:
            return False
#------------------------------------------------------------------
#    Read Measurement6Res attribute
#------------------------------------------------------------------
    def read_Measurement6Res(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Measurement6Res()")
        try:
            os = self._instrument.getMeasurementRes(6)
            attr.set_value(os)
        except Exception,e:
            self.error_stream("Cannot read MeasurementRes6 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
    def is_Measurement6Res_allowed(self, req_type):
        if self._instrument is not None and self.attr_Measurement6_read != 'OFF':
            return True
        else:
            return False
#------------------------------------------------------------------
#    Read Measurement7Res attribute
#------------------------------------------------------------------
    def read_Measurement7Res(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Measurement7Res()")
        try:
            os = self._instrument.getMeasurementRes(7)
            attr.set_value(os)
        except Exception,e:
            self.error_stream("Cannot read MeasurementRes7 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
    def is_Measurement7Res_allowed(self, req_type):
        if self._instrument is not None and self.attr_Measurement7_read != 'OFF':
            return True
        else:
            return False
#------------------------------------------------------------------
#    Read Measurement8Res attribute
#------------------------------------------------------------------
    def read_Measurement8Res(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_Measurement8Res()")
        try:
            os = self._instrument.getMeasurementRes(8)
            attr.set_value(os)
        except Exception,e:
            self.error_stream("Cannot read MeasurementRes8 due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
    def is_Measurement8Res_allowed(self, req_type):
        if self._instrument is not None and self.attr_Measurement8_read != 'OFF':
            return True
        else:
            return False


#------------------------------------------------------------------
#    Read MeasurementGateOnOff attribute
#------------------------------------------------------------------
    def read_MeasurementGateOnOff(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_MeasurementGateOnOff()")
        try:
            self.attr_MeasurementGateOnOff_read = self._instrument.getMeasurementGateOnOff()
            attr.set_value(self.attr_MeasurementGateOnOff_read)
            attr.set_write_value(self.attr_MeasurementGateOnOff_read)
        except Exception,e:
            self.error_stream("Cannot read MeasurementGateOnOff due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write MeasurementGateOnOff attribute
#------------------------------------------------------------------
    def write_MeasurementGateOnOff(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setMeasurementGateOnOff(data)
        except Exception,e:
            self.error_stream("Cannot configure MeasurementGateOnOff due to: %s"%e)

    def is_MeasurementGateOnOff_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False

#------------------------------------------------------------------
#    Read MeasurementGateStart attribute
#------------------------------------------------------------------
    def read_MeasurementGateStart(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_MeasurementGateStart()")
        try:
            self.attr_MeasurementGateStart_read = self._instrument.getMeasurementGateStart()
            attr.set_value(self.attr_MeasurementGateStart_read)
            attr.set_write_value(self.attr_MeasurementGateStart_read)
        except Exception,e:
            self.error_stream("Cannot read MeasurementGateStart due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write MeasurementGateStart attribute
#------------------------------------------------------------------
    def write_MeasurementGateStart(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setMeasurementGateStart(data)
        except Exception,e:
            self.error_stream("Cannot configure MeasurementGateStart due to: %s"%e)

    def is_MeasurementGateStart_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False

#------------------------------------------------------------------
#    Read MeasurementGateStop attribute
#------------------------------------------------------------------
    def read_MeasurementGateStop(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_MeasurementGateStop()")
        try:
            self.attr_MeasurementGateStop_read = self._instrument.getMeasurementGateStop()
            attr.set_value(self.attr_MeasurementGateStop_read)
            attr.set_write_value(self.attr_MeasurementGateStop_read)
        except Exception,e:
            self.error_stream("Cannot read MeasurementGateStop due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
#------------------------------------------------------------------
#    Write MeasurementGateStop attribute
#------------------------------------------------------------------
    def write_MeasurementGateStop(self, attr):
        data = attr.get_write_value()
        try:
            self._instrument.setMeasurementGateStop(data)
        except Exception,e:
            self.error_stream("Cannot configure MeasurementGateStop due to: %s"%e)

    def is_MeasurementGateStop_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False

#------------------------------------------------------------------
#    Read Attribute Hardware
#    Want acquire available and waveform data to be read in order so do it here to be sure
#    Missing some exception handling?
#------------------------------------------------------------------
    def read_attr_hardware(self, data):
        self.debug_stream("In " + self.get_name() + ".read_attr_hardware()")


#==================================================================
#
#    RohdeSchwarzRTO command methods
#
#==================================================================

#------------------------------------------------------------------
#    Start command:
#------------------------------------------------------------------
    @PyTango.DebugIt()
    def Start(self):
        self.debug_stream("In " + self.get_name() +  ".Start()")
        self.change_state(PyTango.DevState.RUNNING)
        print self._instrument.firmware_version
        if self._instrument.firmware_version >= (2,):
            self.acq_thread = Thread(target=self._acquisition_loop)
            self.acq_thread.start()
        else:
            self._instrument.StartAcq()


#------------------------------------------------------------------
#    Is Start command allowed
#------------------------------------------------------------------
    def is_Start_allowed(self):
        self.debug_stream("In " + self.get_name() + ".is_Start_allowed()")
        if self.get_state() in [PyTango.DevState.ON]:
            return True
        else:
            return False
#------------------------------------------------------------------
#    Stop command:
#------------------------------------------------------------------
    def Stop(self):
        self.debug_stream("In " + self.get_name() +  ".Stop()")
        self.change_state(PyTango.DevState.ON)
        if self._instrument.firmware_version >= (2,):
            self._acquiring.clear()
        else:
            self._instrument.StopAcq()
        #self.mymonitor.terminate()

#------------------------------------------------------------------
#    Is Stop command allowed
#------------------------------------------------------------------
    def is_Stop_allowed(self):
        self.debug_stream("In " + self.get_name() + ".is_Stop_allowed()")
        if self.get_state() in [PyTango.DevState.RUNNING,PyTango.DevState.ON]:
            return True
        else:
            return False

#------------------------------------------------------------------
#    Standby command:
#------------------------------------------------------------------
    def Standby(self):
        """ Release the communication with the instrument.
        """
        self.debug_stream("In " + self.get_name() +  ".Standby()")
        if(self._instrument is not None):
            try:
                self._instrument.GoLocal()
                self._instrument.close()
                self._instrument = None
                self.change_state(PyTango.DevState.STANDBY)
                self.set_status("No connection to instrument (standby)")
            except:
                self.error_stream("Cannot disconnect from the instrument")
                self.change_state(PyTango.DevState.FAULT)

#------------------------------------------------------------------
#    Is Standby command allowed
#------------------------------------------------------------------
    def is_Standby_allowed(self):
        self.debug_stream("In " + self.get_name() + ".is_Standby_allowed()")
        if self.get_state() in [PyTango.DevState.ON,PyTango.DevState.RUNNING]:
            return True
        else:
            return False

#------------------------------------------------------------------
#    On command:
#------------------------------------------------------------------
    def On(self):
        """ Establish communication  with the instrument.
        """
        #Undoes the setting to standby, ie makes the connection
        #self.connectInstrument()

#------------------------------------------------------------------
#    Is On command allowed
#------------------------------------------------------------------
    def is_On_allowed(self):
        self.debug_stream("In " + self.get_name() + ".is_On_allowed()")
        if self.get_state() in [PyTango.DevState.STANDBY,PyTango.DevState.RUNNING,PyTango.DevState.ON]:
            return True
        else:
            return False

#==================================================================
#
#    RohdeSchwarzRTOClass class definition
#
#==================================================================
class RohdeSchwarzRTOClass(PyTango.DeviceClass):

    #    Class Properties
    class_property_list = {
        }


    #    Device Properties
    device_property_list = {
        'Instrument':
            [PyTango.DevString,
            "The name of the instrument to use",
            [] ],
        'WaveformAverageChannel':
            [PyTango.DevShort,
            "The channel on which to perform the summing and averaging (1-4)",
            [] ]
        }


    #    Command definitions
    cmd_list = {
        'Start':
            [[PyTango.DevVoid, "none"],
            [PyTango.DevBoolean, "none"]],
        'Stop':
            [[PyTango.DevVoid, "none"],
            [PyTango.DevBoolean, "none"]],
        'On':
            [[PyTango.DevVoid, "none"],
            [PyTango.DevBoolean, "none"]],
        'Standby':
            [[PyTango.DevVoid, "none"],
            [PyTango.DevBoolean, "none"]],
        }


    #    Attribute definitions
    attr_list = {
        'IDN':
            [[PyTango.DevString,
            PyTango.SCALAR,
            PyTango.READ],
            {
                'description': "Instrument identification",
            } ],
        'StateCh1':
            [[PyTango.DevBoolean,
              PyTango.SCALAR,
              PyTango.READ_WRITE],
             {
                'description': "Channel 1 state",
                'label': "Channel 1 state",
                } ],
        'StateCh2':
            [[PyTango.DevBoolean,
              PyTango.SCALAR,
              PyTango.READ_WRITE],
             {
                'description': "Channel 2 state",
                'label': "Channel 2 state",
                } ],
        'StateCh3':
            [[PyTango.DevBoolean,
              PyTango.SCALAR,
              PyTango.READ_WRITE],
             {
                'description': "Channel 3 state",
                'label': "Channel 3 state",
                } ],
        'StateCh4':
            [[PyTango.DevBoolean,
              PyTango.SCALAR,
              PyTango.READ_WRITE],
             {
                'description': "Channel 4 state",
                'label': "Channel 4 state",
                } ],
        'AcquireAvailable':
            [[PyTango.DevLong,
              PyTango.SCALAR,
              PyTango.READ],
             {
                'description': "triggered event count",
                'unit': "events",
                'label': "Triggered events",
                'format': "%4.0f"
                } ],
        #'FixedRecordLength':
        #    [[PyTango.DevBoolean,
        #      PyTango.SCALAR,
        #      PyTango.READ],
        #     {
        #        'description': "Option to ensure fixed record length",
        #        } ],
        'RecordLength':
            [[PyTango.DevLong,
              PyTango.SCALAR,
              PyTango.READ_WRITE],
             {
                'description': "Record length",
                'label': "Record length",
                'min value': 1000,
                'max value': 1000000,
                'unit': "Samples",
                'format': "%4.0f"
                } ],
        'HScale':
            [[PyTango.DevDouble,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "Time scale",
                'label': "Horizontal (time) scale",
                'unit': "s",
                'min value': 1e-8,
                'max value': 1.0,
                'format': "%7.4f"
            } ],

        'Trig1Source':
            [[PyTango.DevString,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "Source input for trigger 1",
                'label': "Trigger 1 source",
            } ],

        'Trig1Mode':
            [[PyTango.DevString,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "Mode for trigger 1",
                'label': "Trigger 1 mode",
            } ],

        'TrigLevel':
            [[PyTango.DevDouble,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "External trigger level",
                'label': "External trigger level",
                'unit': "V",
                'min value': -10.0,
                'max value': 10.0,
                'format': "%4.3f"
            } ],

        'OffsetCh1':
            [[PyTango.DevDouble,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "Offset channel 1",
                'label': "Offset channel 1",
                'unit': "V",
                'format': "%4.3f"
            } ],
        'VScaleCh1':
            [[PyTango.DevDouble,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "VScale channel 1",
                'label': "Vertical scale channel 1",
                'unit': "V",
                'format': "%4.3f"
            } ],
        'TimeScale':
            [[PyTango.DevDouble,
            PyTango.SPECTRUM,
            PyTango.READ, 10000],
            {
                'description': "Time scale",
                'label': "Time scale",
                'unit': "s"
            } ],
        'WaveformSumCh1':
            [[PyTango.DevDouble,
            PyTango.SCALAR,
            PyTango.READ],
            {
                'description': "WaveformSum channel 1",
                'label': "Waveform Sum channel 1",
            } ],
        'WaveformDataCh1':
            [[PyTango.DevShort,
            PyTango.SPECTRUM,
            PyTango.READ, 10000],
            {
                'description': "WaveformData channel 1",
                'label': "Channel 1",
                'unit': "V"
            } ],
        'OffsetCh2':
            [[PyTango.DevDouble,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "Offset channel 2",
                'label': "Offset channel 2",
                'unit': "V",
                'format': "%4.3f"
            } ],
        'VScaleCh2':
            [[PyTango.DevDouble,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "VScale channel 2",
                'label': "Vertical scale channel 2",
                'unit': "V",
                'format': "%4.3f"
            } ],
        'WaveformSumCh2':
            [[PyTango.DevDouble,
            PyTango.SCALAR,
            PyTango.READ],
            {
                'description': "WaveformSum channel 2",
                'label': "Waveform Sum channel 2",
            } ],
        'WaveformDataCh2':
            [[PyTango.DevShort,
            PyTango.SPECTRUM,
            PyTango.READ, 10000],
            {
                'description': "WaveformData channel 2",
                'label': "Channel 2",
                'unit': "V"
            } ],
        'OffsetCh3':
            [[PyTango.DevDouble,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "Offset channel 3",
                'label': "Offset channel 3",
                'unit': "V",
                'format': "%4.3f"
            } ],
        'VScaleCh3':
            [[PyTango.DevDouble,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "VScale channel 3",
                'label': "Vertical scale channel 3",
                'unit': "V",
                'format': "%4.3f"
            } ],
        'WaveformSumCh3':
            [[PyTango.DevDouble,
            PyTango.SCALAR,
            PyTango.READ],
            {
                'description': "WaveformSum channel 3",
                'label': "Waveform Sum channel 3",
            } ],
        'WaveformDataCh3':
            [[PyTango.DevShort,
            PyTango.SPECTRUM,
            PyTango.READ, 10000],
            {
                'description': "WaveformData channel 3",
                'label': "Channel 3",
                'unit': "V"
            } ],
        'OffsetCh4':
            [[PyTango.DevDouble,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "Offset channel 4",
                'label': "Offset channel 4",
                'unit': "V",
                'format': "%4.3f"
            } ],
        'VScaleCh4':
            [[PyTango.DevDouble,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "VScale channel 4",
                'label': "Vertical scale channel 4",
                'unit': "V",
                'format': "%4.3f"
            } ],
        'WaveformSumCh4':
            [[PyTango.DevShort,
            PyTango.SCALAR,
            PyTango.READ],
            {
                'description': "WaveformSum channel 4",
                'label': "Waveform Sum channel 4",
            } ],
        'WaveformDataCh4':
            [[PyTango.DevDouble,
            PyTango.SPECTRUM,
            PyTango.READ, 10000],
            {
                'description': "WaveformData channel 4",
                'label': "Channel 4",
                'unit': "V"
            } ],
        'Measurement1':
            [[PyTango.DevString,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "Configure measurement 1",
                'label': "Configure measurement 1",
            } ],
        'Measurement2':
            [[PyTango.DevString,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "Configure measurement 2",
                'label': "Configure measurement 2",
            } ],
        'Measurement3':
            [[PyTango.DevString,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "Configure measurement 3",
                'label': "Configure measurement 3",
            } ],
        'Measurement4':
            [[PyTango.DevString,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "Configure measurement 4",
                'label': "Configure measurement 4",
            } ],
        'Measurement5':
            [[PyTango.DevString,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "Configure measurement 5",
                'label': "Configure measurement 5",
            } ],
        'Measurement6':
            [[PyTango.DevString,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "Configure measurement 6",
                'label': "Configure measurement 6",
            } ],
        'Measurement7':
            [[PyTango.DevString,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "Configure measurement 7",
                'label': "Configure measurement 7",
            } ],
        'Measurement8':
            [[PyTango.DevString,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "Configure measurement 8",
                'label': "Configure measurement 8",
            } ],

        'Measurement1Source':
            [[PyTango.DevString,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "Source measurement 1",
                'label': "Source measurement 1",
            } ],

        'Measurement2Source':
            [[PyTango.DevString,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "Source measurement 2",
                'label': "Source measurement 2",
            } ],

        'Measurement3Source':
            [[PyTango.DevString,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "Source measurement 3",
                'label': "Source measurement 3",
            } ],

        'Measurement4Source':
            [[PyTango.DevString,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "Source measurement 4",
                'label': "Source measurement 4",
            } ],

        'Measurement5Source':
            [[PyTango.DevString,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "Source measurement 5",
                'label': "Source measurement 5",
            } ],

        'Measurement6Source':
            [[PyTango.DevString,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "Source measurement 6",
                'label': "Source measurement 6",
            } ],

        'Measurement7Source':
            [[PyTango.DevString,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "Source measurement 7",
                'label': "Source measurement 7",
            } ],

        'Measurement8Source':
            [[PyTango.DevString,
            PyTango.SCALAR,
            PyTango.READ_WRITE],
            {
                'description': "Source measurement 8",
                'label': "Source measurement 8",
            } ],

        'Measurement1Res':
            [[PyTango.DevDouble,
            PyTango.SCALAR,
            PyTango.READ],
            {
                'description': "Result measurement 1",
                'label': "Result measurement 1",
                'format': "%.3e"
            } ],
        'Measurement2Res':
            [[PyTango.DevDouble,
            PyTango.SCALAR,
            PyTango.READ],
            {
                'description': "Result measurement 2",
                'label': "Result measurement 2",
                'format': "%.3e"
            } ],
        'Measurement3Res':
            [[PyTango.DevDouble,
            PyTango.SCALAR,
            PyTango.READ],
            {
                'description': "Result measurement 3",
                'label': "Result measurement 3",
                'format': "%.3e"
            } ],
        'Measurement4Res':
            [[PyTango.DevDouble,
            PyTango.SCALAR,
            PyTango.READ],
            {
                'description': "Result measurement 4",
                'label': "Result measurement 4",
                'format': "%.3e"
            } ],
        'Measurement5Res':
            [[PyTango.DevDouble,
            PyTango.SCALAR,
            PyTango.READ],
            {
                'description': "Result measurement 5",
                'label': "Result measurement 5",
                'format': "%.3e"
            } ],
        'Measurement6Res':
            [[PyTango.DevDouble,
            PyTango.SCALAR,
            PyTango.READ],
            {
                'description': "Result measurement 6",
                'label': "Result measurement 6",
                'format': "%.3e"
            } ],
        'Measurement7Res':
            [[PyTango.DevDouble,
            PyTango.SCALAR,
            PyTango.READ],
            {
                'description': "Result measurement 7",
                'label': "Result measurement 7",
                'format': "%.3e"
            } ],
        'Measurement8Res':
            [[PyTango.DevDouble,
            PyTango.SCALAR,
            PyTango.READ],
            {
                'description': "Result measurement 8",
                'label': "Result measurement 8",
                'format': "%.3e"
            } ],

        'MeasurementGateOnOff':
            [[PyTango.DevBoolean,
              PyTango.SCALAR,
              PyTango.READ_WRITE],
             {
                'description': "Gating for measurements enabled/disabled",
                'label': "Gating for measurements",
                } ],
        'MeasurementGateStart':
            [[PyTango.DevDouble,
              PyTango.SCALAR,
              PyTango.READ_WRITE],
             {
                'description': "Gate for measurements start",
                'label': "Gate for measurements start",
                } ],
        'MeasurementGateStop':
            [[PyTango.DevDouble,
              PyTango.SCALAR,
              PyTango.READ_WRITE],
             {
                'description': "Gate for measurements stop",
                'label': "Gate for measurements stop",
                } ],
        'CouplingCh1':
            [[PyTango.DevString,
              PyTango.SCALAR,
              PyTango.READ_WRITE],
             {
                'description': "Coupling channel 1",
                'label': "Coupling channel 1",
                } ],
        'CouplingCh2':
            [[PyTango.DevString,
              PyTango.SCALAR,
              PyTango.READ_WRITE],
             {
                'description': "Coupling channel 2",
                'label': "Coupling channel 2",
                } ],
        'CouplingCh3':
            [[PyTango.DevString,
              PyTango.SCALAR,
              PyTango.READ_WRITE],
             {
                'description': "Coupling channel 3",
                'label': "Coupling channel 3",
                } ],
        'CouplingCh4':
            [[PyTango.DevString,
              PyTango.SCALAR,
              PyTango.READ_WRITE],
             {
                'description': "Coupling channel 4",
                'label': "Coupling channel 4",
                } ],
        # 'SpecialWaveform':
        #     [[PyTango.DevDouble,
        #     PyTango.SPECTRUM,
        #     PyTango.READ, 10000],
        #     {
        #         'description': "Special Waveform Data",
        #         'label': "Waveform",
        #         'unit': "V"
        #     } ]

        }



#------------------------------------------------------------------
#    RohdeSchwarzRTOClass Constructor
#------------------------------------------------------------------
    def __init__(self, name):
        PyTango.DeviceClass.__init__(self, name)
        self.set_type(name);

#==================================================================
#
#    RohdeSchwarzRTO class main method
#
#==================================================================
def main():
    try:
        py = PyTango.Util(sys.argv)
        py.add_class(RohdeSchwarzRTOClass, RohdeSchwarzRTO, 'RohdeSchwarzRTO')

        U = PyTango.Util.instance()
        U.server_init()
        U.server_run()

    except PyTango.DevFailed,e:
        print '-------> Received a DevFailed exception:',e
    except Exception,e:
        print '-------> An unforeseen exception occured....',e

if __name__ == '__main__':
    main()
