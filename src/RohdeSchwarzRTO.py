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
#from threading import Thread
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

    myWaveformSumCh1=0
    myWaveformDataCh1=None
    myWaveformSumCh2=0
    myWaveformSumCh3=0
    myWaveformSumCh4=0
    state_refresh_interval_seconds = 10

    def change_state(self,newstate):
        self.debug_stream("In %s.change_state(%s)"%(self.get_name(),str(newstate)))
        if newstate != self.get_state():
            self.set_state(newstate)
          
    def connectInstrument(self):
        self._instrument = None
        self._instrument =  RohdeSchwarzRTOConnection(self.Instrument,self.Port)
        try:
            self._instrument.connect()
            self._idn = self._instrument.getIDN()
        except Exception,e:
            self.error_stream("In %s.connectInstrument() Cannot connect "\
                              "to the instrument due to: %s"%(self.get_name(),e))
            traceback.print_exc()
            self.change_state(PyTango.DevState.FAULT)
            self.set_status("Could not connect to hardware. Check connection and do INIT.")
            self._instrument = None
            return False
        else:
            self.info_stream("In %s.connectInstrument() Connected to "\
                             "the instrument and "\
                             "identified as: %s"%(self.get_name(),repr(self._idn)))
            self.change_state(PyTango.DevState.ON)
            return True

        #def startMonitoring(self):
        #start a thread to check trigger
        #print "START MON"
        #self.monitorThread.start()
        
        #def endMonitoring(self):
        #end thread to check trigger
        #print "STOP MON"
        #self.monitor.terminate()
        #self.monitorThread.join()

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
        #self.attr_FixedRecordLength_write = True
        self.attr_RecordLength_read = 0
        self.attr_RecordLength_write = 0
        self.attr_HScale_read  = 0
        self.attr_HScale_write = 0

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
        #if not self.__buildInstrumentObj():
        #    return
        if not self.connectInstrument():
            return

        #once connected check if already running or not. 
        tango_status, status_str = self._instrument.getOperCond()
        self.change_state(tango_status)

        #switch all channels on by default
        self._instrument.AllChannelsOn()
        #self.Start()
        #----- PROTECTED REGION END -----#	//	RohdeSchwarzRTO.init_device

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
        except Exception,e:
            self.error_stream("In %s.always_executed_hook() Cannot connect "\
                              "to the instrument due to: %s"%(self.get_name(),e))
            traceback.print_exc()
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
        try:
            #self.attr_Idn_read = self._idn
            #attr.set_value(self.attr_Idn_read)
            attr.set_value(self._idn)
        except:
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return
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
            currentdata = self._instrument.getWaveformData(1)
            currentsum  = self._instrument.sumWaveform(currentdata)
            print "ASKING ACQUIRE AVAILABLE", int(os), currentsum
            #need next line for client - client will ask for wform sum, but only
            #acquire available is polled, so need to set global her for wfs to find
            #VH - should really ask for count and waveform data in same command
            #to ensure synchronisation! ie that wf i goes with trigger i
            self.myWaveformDataCh1 = currentdata
            self.myWaveformSumCh1 = currentsum
            #self.attr_WaveformSumCh1_read = currentsum
        except:
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return

#------------------------------------------------------------------
#    Read FixedRecordLength attribute
#------------------------------------------------------------------
    def read_FixedRecordLength(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_FixedRecordLength()")
        try:
            #print "ASKING FixedRecordLength "
            os = self._instrument.getFixedRecordLength()
            #print os
            attr.set_value(os)
            #attr.set_write_value(os)
        except:
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return

#------------------------------------------------------------------
#    Read RecordLength attribute
#------------------------------------------------------------------
    def read_RecordLength(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_RecordLength()")
        try:
            #print "ASKING RecordLength "
            os = self._instrument.getRecordLength()
            #print os
            attr.set_value(os)
            attr.set_write_value(os)
        except:
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
            return

#------------------------------------------------------------------
#    Write RecordLength attribute
#------------------------------------------------------------------
    def write_RecordLength(self, attr):
        #set to fixed record length first
        self._instrument.setFixedRecordLength()
        #now set value
        data = attr.get_write_value()
        #try:  
        self._instrument.setRecordLength(data)
        #except:
    def is_RecordLength_allowed(self, req_type):
        #if self.get_state() in [PyTango.DevState.ON]:
        #    return True
        #else:
        #   return False
        return True

#------------------------------------------------------------------
#    Read WaveformSumCh1 attribute
#------------------------------------------------------------------
    def read_WaveformSumCh1(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_WaveformSumCh1()")
        try:
            #if self.myWaveformDataCh1 is not None: 
            #mysum = self._instrument.sumWaveform(self.myWaveformDataCh1)
            #else:
            #self.myWaveformDataCh1 = self._instrument.getWaveformData(1)
            #mysum = self._instrument.sumWaveform(self.myWaveformDataCh1)
            attr.set_value(self.myWaveformSumCh1)
        except:
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)

#------------------------------------------------------------------
#    Read WaveformSumCh2 attribute
#------------------------------------------------------------------
    def read_WaveformSumCh2(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_WaveformSumCh2()")
        try:
            attr.set_value(self.myWaveformSumCh2)
        except:
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
#------------------------------------------------------------------
#    Read WaveformSumCh3 attribute
#------------------------------------------------------------------
    def read_WaveformSumCh3(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_WaveformSumCh3()")
        try:
            attr.set_value(self.myWaveformSumCh3)
        except:
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
#------------------------------------------------------------------
#    Read WaveformSumCh4 attribute
#------------------------------------------------------------------
    def read_WaveformSumCh4(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_WaveformSumCh4()")
        try:
            attr.set_value(self.myWaveformSumCh4)
        except:
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)


#------------------------------------------------------------------
#    Read WaveformDataCh1 attribute
#------------------------------------------------------------------
# SPECIAL CASE FOR CHANNEL 1
# DO NOT READ HW HERE SINCE ALREADY READ IN THE ACQUIRE AVAILABLE ATTRIBUTE READING

    def read_WaveformDataCh1(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_WaveformDataCh1()")
        try:
            if self.myWaveformDataCh1 == None:
               self.myWaveformDataCh1 = self._instrument.getWaveformData(1)
            attr.set_value(self.myWaveformDataCh1)
            #data = self._instrument.getWaveformData(1)
            #attr.set_value(data)
            #self.myWaveformSumCh1=self._instrument.sumWaveform(data)
            self.myWaveformDataCh1 = None
        except:
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
#------------------------------------------------------------------
#    Read WaveformDataCh2 attribute
#------------------------------------------------------------------
    def read_WaveformDataCh2(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_WaveformDataCh2()")
        try:
            data = self._instrument.getWaveformData(2)
            attr.set_value(data)
            self.myWaveformSumCh2=self._instrument.sumWaveform(data)
        except:
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
#------------------------------------------------------------------
#    Read WaveformDataCh3 attribute
#------------------------------------------------------------------
    def read_WaveformDataCh3(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_WaveformDataCh3()")
        try:
            data = self._instrument.getWaveformData(3)
            attr.set_value(data)
            self.myWaveformSumCh3=self._instrument.sumWaveform(data)
        except:
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
#------------------------------------------------------------------
#    Read WaveformDataCh4 attribute
#------------------------------------------------------------------
    def read_WaveformDataCh4(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_WaveformDataCh4()")
        try:
            data = self._instrument.getWaveformData(4)
            attr.set_value(data)
            self.myWaveformSumCh4=self._instrument.sumWaveform(data)
        except:
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)


#------------------------------------------------------------------
#    Read OffsetCh1 attribute
#------------------------------------------------------------------
    def read_OffsetCh1(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_OffsetCh1()")
        try:
            os = self._instrument.getOffset(1)
            attr.set_value(os)  
            attr.set_write_value(os)
        except:
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
#------------------------------------------------------------------
#    Read OffsetCh2 attribute
#------------------------------------------------------------------
    def read_OffsetCh2(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_OffsetCh2()")
        try:
            os = self._instrument.getOffset(2)
            attr.set_value(os)  
            attr.set_write_value(os)
        except:
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
#------------------------------------------------------------------
#    Read OffsetCh3 attribute
#------------------------------------------------------------------
    def read_OffsetCh3(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_OffsetCh3()")
        try:
            os = self._instrument.getOffset(3)
            attr.set_value(os)  
            attr.set_write_value(os)
        except:
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
#------------------------------------------------------------------
#    Read OffsetCh4 attribute
#------------------------------------------------------------------
    def read_OffsetCh4(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_OffsetCh4()")
        try:
            os = self._instrument.getOffset(4)
            attr.set_value(os)  
            attr.set_write_value(os)
        except:
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)

#------------------------------------------------------------------
#    Write OffsetCh1 attribute
#------------------------------------------------------------------
    def write_OffsetCh1(self, attr):
        data = attr.get_write_value()
        #try:  
        self._instrument.setOffset(1,data)
        #except:
    def is_OffsetCh1_allowed(self, req_type):
        return True
#------------------------------------------------------------------
#    Write OffsetCh2 attribute
#------------------------------------------------------------------
    def write_OffsetCh2(self, attr):
        data = attr.get_write_value()
        #try:  
        self._instrument.setOffset(2,data)
        #except:
    def is_OffsetCh2_allowed(self, req_type):
        return True
#------------------------------------------------------------------
#    Write OffsetCh3 attribute
#------------------------------------------------------------------
    def write_OffsetCh3(self, attr):
        data = attr.get_write_value()
        #try:  
        self._instrument.setOffset(3,data)
        #except:
    def is_OffsetCh3_allowed(self, req_type):
        return True
#------------------------------------------------------------------
#    Write OffsetCh4 attribute
#------------------------------------------------------------------
    def write_OffsetCh4(self, attr):
        data = attr.get_write_value()
        #try:  
        self._instrument.setOffset(4,data)
        #except:
    def is_OffsetCh4_allowed(self, req_type):
        return True


#------------------------------------------------------------------
#    Read VScaleCh1 attribute
#------------------------------------------------------------------
    def read_VScaleCh1(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_VScaleCh1()")
        try:
            os = self._instrument.getVScale(1)
            attr.set_value(os)  
            attr.set_write_value(os)
        except:
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
#------------------------------------------------------------------
#    Read VScaleCh2 attribute
#------------------------------------------------------------------
    def read_VScaleCh2(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_VScaleCh2()")
        try:
            os = self._instrument.getVScale(2)
            attr.set_value(os)  
            attr.set_write_value(os)
        except:
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
#------------------------------------------------------------------
#    Read VScaleCh3 attribute
#------------------------------------------------------------------
    def read_VScaleCh3(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_VScaleCh3()")
        try:
            os = self._instrument.getVScale(3)
            attr.set_value(os)  
            attr.set_write_value(os)
        except:
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)
#------------------------------------------------------------------
#    Read VScaleCh4 attribute
#------------------------------------------------------------------
    def read_VScaleCh4(self, attr):
        self.debug_stream("In " + self.get_name() + ".read_VScaleCh4()")
        try:
            os = self._instrument.getVScale(4)
            attr.set_value(os)  
            attr.set_write_value(os)
        except:
            attr.set_value_date_quality("",time.time(),PyTango.AttrQuality.ATTR_INVALID)

#------------------------------------------------------------------
#    Write VScaleCh1 attribute
#------------------------------------------------------------------
    def write_VScaleCh1(self, attr):
        data = attr.get_write_value()
        #try:  
        self._instrument.setVScale(1,data)
        #except:
    def is_VScaleCh1_allowed(self, req_type):
        return True
#------------------------------------------------------------------
#    Write VScaleCh2 attribute
#------------------------------------------------------------------
    def write_VScaleCh2(self, attr):
        data = attr.get_write_value()
        #try:  
        self._instrument.setVScale(2,data)
        #except:
    def is_VScaleCh2_allowed(self, req_type):
        return True
#------------------------------------------------------------------
#    Write VScaleCh3 attribute
#------------------------------------------------------------------
    def write_VScaleCh3(self, attr):
        data = attr.get_write_value()
        #try:  
        self._instrument.setVScale(3,data)
        #except:
    def is_VScaleCh3_allowed(self, req_type):
        return True
#------------------------------------------------------------------
#    Write VScaleCh4 attribute
#------------------------------------------------------------------
    def write_VScaleCh4(self, attr):
        data = attr.get_write_value()
        #try:  
        self._instrument.setVScale(4,data)
        #except:
    def is_VScaleCh4_allowed(self, req_type):
        return True

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
        #try:  
        self._instrument.setHScale(data)
        #except:
    def is_HScale_allowed(self, req_type):
        return True

#------------------------------------------------------------------
#    Read Attribute Hardware
#------------------------------------------------------------------
    def read_attr_hardware(self, data):
        self.debug_stream("In " + self.get_name() + ".read_attr_hardware()")
        #----- PROTECTED REGION ID(RohdeSchwarzRTO.read_attr_hardware) ENABLED START -----#
        #----- PROTECTED REGION END -----#	//	RohdeSchwarzRTO.read_attr_hardware


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
        if not self.connectInstrument():
            return

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
#        'Off':
#            [[PyTango.DevVoid, "none"],
#            [PyTango.DevBoolean, "none"]],
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
