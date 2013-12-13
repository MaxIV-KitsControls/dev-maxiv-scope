import PyTango
import time

class CB(object):

    def push_event(self, ev_data):
        #if event.attr_value is not None:
        print("%s: event %s waveform sum %s"%(time.time(),ev_data.device.AcquireAvailable,ev_data.device.WaveformSumCh1 ))
              #else:
              #    print("ERROR!!!")
              #    print event
        
dev=PyTango.DeviceProxy('scope/rohdeschwarz/rto-2')
cb=CB()


dev.subscribe_event('AcquireAvailable',PyTango.EventType.CHANGE_EVENT,cb, [] )

while True:
    time.sleep(1)
