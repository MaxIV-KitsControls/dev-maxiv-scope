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
import socket
from threading import Thread
import time
import traceback
import numpy,struct,copy
from types import StringType
from rohdeschwarzrtolib import RohdeSchwarzRTOConnection
from monitor import Monitor

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

    myWaveformDataCh1=None
    myWaveformDataCh2=None
    myWaveformDataCh3=None
    myWaveformDataCh4=None
    myWaveformSumCh1=0
    myWaveformSumCh2=0
    myWaveformSumCh3=0
    myWaveformSumCh4=0
    state_refresh_interval_seconds = 10

    def change_state(self,newstate):
        self.debug_stream("In %s.change_state(%s)"%(self.get_name(),str(newstate)))
        if newstate != self.get_state():
            self.set_state(newstate)
          
    def connectInstrument(self):
        self._idn = "unknown"
        self._instrument =  RohdeSchwarzRTOConnection(self.Instrument,self.Port)
        try:
            self._instrument.connect()
            self._idn = self._instrument.getIDN()
        #Good to catch timeout specifically
        except socket.timeout:
            self.set_status("Cannot connect to instrument (timeout). Check and do INIT")
            self.set_state(PyTango.DevState.FAULT)
            self._instrument = None #PJB needed to prevent client trying to read other attributes
        except Exception,e:
            self.error_stream("In %s.connectInstrument() Cannot connect due to: %s"%(self.get_name(),e))
            traceback.print_exc()
            self.change_state(PyTango.DevState.FAULT)
            self.set_status("Could not connect to hardware. Check connection and do INIT.")
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
        RohdeSchwarzRTO.init_device(self)

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
        self.attr_FixedRecordLength_read = True
        self.attr_RecordLength_read = 0
        self.attr_RecordLength_write = 0
        self.attr_HScale_read  = 0
        self.attr_HScale_write = 0
        self.attr_TrigLevel_read  = 0
        self.attr_TrigLevel_write = 0

        #Per channel attributes
        self.attr_WaveformDataCh1_read = 0
        self.attr_WaveformSumCh1_read = 0
        self.attr_OffsetCh1_read = 0
        self.attr_OffsetCh1_write = 0
        self.attr_VScaleCh1_read = 0
        self.attr_VScaleCh1_write = 0
        #
        self.attr_WaveformDataCh2_read = 0
        self.attr_WaveformSumCh2_read = 0
        self.attr_OffsetCh2_read = 0
        self.attr_OffsetCh2_write = 0
        self.attr_VScaleCh2_read = 0
        self.attr_VScaleCh2_write = 0
        #
        self.attr_WaveformDataCh3_read = 0
        self.attr_WaveformSumCh3_read = 0
        self.attr_OffsetCh3_read = 0
        self.attr_OffsetCh3_write = 0
        self.attr_VScaleCh3_read = 0
        self.attr_VScaleCh3_write = 0
        #
        self.attr_WaveformDataCh4_read = 0
        self.attr_WaveformSumCh4_read = 0
        self.attr_OffsetCh4_read = 0
        self.attr_OffsetCh4_write = 0
        self.attr_VScaleCh4_read = 0
        self.attr_VScaleCh4_write = 0

        
        #---- once initialized, begin the process to connect with the instrument
        #PJB push trigger count
        #self.set_change_event("AcquireAvailable", True)
        self._instrument = None
        if not self.connectInstrument():
            return

        #once connected check if already running or not. 
        tango_status, status_str = self._instrument.getOperCond()
        self.change_state(tango_status)

        #switch all channels on by default
        self._instrument.AllChannelsOn()

        #pjb xxx monitor thread
        #self.mymonitor = Monitor()
        #self.event_thread = Thread(target=self.mymonitor.run,args=(100,self._instrument))

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
        try:
            os = self._instrument.getCount()
            #PJB xxx self.push_change_event("AcquireAvailable", int(os))
            attr.set_value(int(os))  
            # PJB xxx need to read wave form and get sum here, if this counter is polled
            #need next line for client - client will ask for wform sum, but only
            #acquire available is polled, so need to set global her for wfs to find
            #VH - should really ask for count and waveform data in same command
            #to ensure synchronisation! ie that wf i goes with trigger i
            currentdata = self._instrument.getWaveformData(1)
            self.myWaveformDataCh1 = currentdata
            self.myWaveformSumCh1 = self._instrument.sumWaveform(currentdata)
            currentdata = self._instrument.getWaveformData(2)
            self.myWaveformDataCh2 = currentdata
            self.myWaveformSumCh2 = self._instrument.sumWaveform(currentdata)
            currentdata = self._instrument.getWaveformData(3)
            self.myWaveformDataCh3 = currentdata
            self.myWaveformSumCh3 = self._instrument.sumWaveform(currentdata)
            currentdata = self._instrument.getWaveformData(4)
            self.myWaveformDataCh4 = currentdata
            self.myWaveformSumCh4 = self._instrument.sumWaveform(currentdata)
        except Exception,e:
            self.error_stream("Cannot read AcquireAvailable due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
    def is_AcquireAvailable_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False
#------------------------------------------------------------------
#    Read FixedRecordLength attribute
#------------------------------------------------------------------
    def read_FixedRecordLength(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_FixedRecordLength()")
        try:
            os = self._instrument.getFixedRecordLength()
            attr.set_value(os)
        except Exception,e:
            self.error_stream("Cannot read FixedRecordLength due to: %s"%e)
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
    def is_FixedRecordLength_allowed(self, req_type):
        if self._instrument is not None:
            return True
        else:
            return False
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
#------------------------------------------------------------------
    def write_RecordLength(self, attr):
        #set to fixed record length first
        self._instrument.setFixedRecordLength()
        #now set value
        data = attr.get_write_value()
        self._instrument.setRecordLength(data)
#------------------------------------------------------------------
#    Read WaveformSumCh1 attribute
#------------------------------------------------------------------
    def read_WaveformSumCh1(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_WaveformSumCh1()")
        #not read from hw here
        attr.set_value(self.myWaveformSumCh1)

#------------------------------------------------------------------
#    Read WaveformSumCh2 attribute
#------------------------------------------------------------------
    def read_WaveformSumCh2(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_WaveformSumCh2()")
        #not read from hw here
        attr.set_value(self.myWaveformSumCh2)
#------------------------------------------------------------------
#    Read WaveformSumCh3 attribute
#------------------------------------------------------------------
    def read_WaveformSumCh3(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_WaveformSumCh3()")
        #not read from hw here
        attr.set_value(self.myWaveformSumCh3)
#------------------------------------------------------------------
#    Read WaveformSumCh4 attribute
#------------------------------------------------------------------
    def read_WaveformSumCh4(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_WaveformSumCh4()")
        #not read from hw here
        attr.set_value(self.myWaveformSumCh4)
#------------------------------------------------------------------
#    Read WaveformDataCh1 attribute
#------------------------------------------------------------------
# DO NOT READ HW HERE IF ALREADY READ IN THE ACQUIRE AVAILABLE ATTRIBUTE READING
# THIS SHOULD BE IN READ ATTRIB HW! CAN IT EVER BE NONE?
    def read_WaveformDataCh1(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_WaveformDataCh1()")
        try:
            if self.myWaveformDataCh1 is None:
               self.myWaveformDataCh1 = self._instrument.getWaveformData(1)
            attr.set_value(self.myWaveformDataCh1)
            self.myWaveformDataCh1 = None
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
            if self.myWaveformDataCh2 is None:
               self.myWaveformDataCh2 = self._instrument.getWaveformData(2)
            attr.set_value(self.myWaveformDataCh2)
            self.myWaveformDataCh2 = None
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
            if self.myWaveformDataCh3 is None:
               self.myWaveformDataCh3 = self._instrument.getWaveformData(3)
            attr.set_value(self.myWaveformDataCh3)
            self.myWaveformDataCh3 = None
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
            if self.myWaveformDataCh4 is None:
               self.myWaveformDataCh4 = self._instrument.getWaveformData(4)
            attr.set_value(self.myWaveformDataCh4)
            self.myWaveformDataCh4 = None
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
        except:
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)

#------------------------------------------------------------------
#    Write HScale attribute
#------------------------------------------------------------------
    def write_HScale(self, attr):
        data = attr.get_write_value()
        self._instrument.setHScale(data)
    def is_HScale_allowed(self, req_type):
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
#    Read Attribute Hardware
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
        self._instrument.StartAcq()
        #self.event_thread.start()


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
        self.connectInstrument()

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
        'Port':
            [PyTango.DevUShort,
            "In case of socket interface the port value can be changed",
            [5025]],
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
        'FixedRecordLength':
            [[PyTango.DevBoolean,
              PyTango.SCALAR,
              PyTango.READ],
             {
                'description': "Option to ensure fixed record length",
                } ],
        'RecordLength':
            [[PyTango.DevLong,
              PyTango.SCALAR,
              PyTango.READ_WRITE],
             {
                'description': "Record length",
                'label': "Record length",
                'min value': 1000,
                'max value': 200000,
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
                'min value': 0.000001,
                'max value': 1.0,
                'format': "%7.4f"
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
        'WaveformSumCh1':
            [[PyTango.DevDouble,
            PyTango.SCALAR,
            PyTango.READ],
            {
                'description': "WaveformSum channel 1",
                'label': "Waveform Sum channel 1",
            } ],
        'WaveformDataCh1':
            [[PyTango.DevDouble,
            PyTango.SPECTRUM,
            PyTango.READ, 200000],
            {
                'description': "WaveformData channel 1",
                'label': "Waveform Data channel 1",
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
            [[PyTango.DevDouble,
            PyTango.SPECTRUM,
            PyTango.READ, 200000],
            {
                'description': "WaveformData channel 2",
                'label': "Waveform Data channel 2",
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
            [[PyTango.DevDouble,
            PyTango.SPECTRUM,
            PyTango.READ, 200000],
            {
                'description': "WaveformData channel 3",
                'label': "Waveform Data channel 3",
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
            [[PyTango.DevDouble,
            PyTango.SCALAR,
            PyTango.READ],
            {
                'description': "WaveformSum channel 4",
                'label': "Waveform Sum channel 4",
            } ],
        'WaveformDataCh4':
            [[PyTango.DevDouble,
            PyTango.SPECTRUM,
            PyTango.READ, 200000],
            {
                'description': "WaveformData channel 4",
                'label': "Waveform Data channel 4",
            } ],
        }



#------------------------------------------------------------------
#    RohdeSchwarzRTOClass Constructor
#------------------------------------------------------------------
    def __init__(self, name):
        PyTango.DeviceClass.__init__(self, name)
        self.set_type(name);
        print "In RohdeSchwarzRTO Class  constructor"

#==================================================================
#
#    RohdeSchwarzRTO class main method
#
#==================================================================
def main():
    try:
        py = PyTango.Util(sys.argv)
        py.add_class(RohdeSchwarzRTOClass,RohdeSchwarzRTO,'RohdeSchwarzRTO')

        U = PyTango.Util.instance()
        U.server_init()
        U.server_run()

    except PyTango.DevFailed,e:
        print '-------> Received a DevFailed exception:',e
    except Exception,e:
        print '-------> An unforeseen exception occured....',e

if __name__ == '__main__':
    main()
