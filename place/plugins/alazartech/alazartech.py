"""PLACE module to control AlazarTech cards"""
import json
from time import sleep
from ctypes import c_void_p
from obspy import Trace, UTCDateTime
import numpy as np
import matplotlib.pyplot as plt

from place.plugins.instrument import Instrument
from . import atsapi as ats
setattr(ats, 'TRIG_FORCE', -1)

class ATSGeneric(Instrument, ats.Board):
    """Class which supports all Alazar controllers.

    This class should be overridden if classes are needed for specific cards.

    Note: This class currently only supports boards providing data in an
    unsigned, 2 bytes per sample, format. It should support 12, 14, and 16 bits
    per sample. If 8 bits per sample is desired, that functionality will need
    to be added to this class.
    """
    _bytes_per_sample = 2
    _data_type = np.dtype('<u'+str(_bytes_per_sample)) # (<)little-endian, (u)unsigned

    def __init__(self):
        """Constructor"""
        Instrument.__init__(self)
        ats.Board.__init__(self)
        self._config = None
        self._analog_inputs = None

# PUBLIC METHODS

    def config(self, header, config_string):
        """Configure the Alazar card

        This method is responsible for reading all the data from the
        configuration input and setting up the card for scanning.

        From the ATS-SDK-Guide...
            "Before acquiring data from a board system, an application must
            configure the timebase, analog inputs, and trigger system settings
            for each board in the board system."

        After configuring the board, this method also performs the first data
        acquisition steps by setting the record size and the record count.

        :param header: metadata for the scan
        :type header: obspy.core.trace.Stats

        :param config_string: the JSON-formatted configuration
        :type config_string: str
        """
        # store JSON data
        self._config = json.loads(config_string)
        # execute configuration commands on the card
        self._config_timebase(header)
        self._config_analog_inputs()
        self._config_trigger_system()
        self._config_record(header)

    def update(self, header):
        """Record a trace using the current configuration

        :param header: metadata for the scan
        :type header: obspy.core.trace.Stats
        """
        header.starttime = UTCDateTime()
        self.startCapture()
        self._wait_for_trigger()
        for analog_input in self._analog_inputs:
            channel = analog_input.get_input_channel()
            record = self._read_to_record(channel)
            max_volts = _input_range_to_volts(analog_input.get_input_range())
            volt_data = self._convert_to_volts(record, max_volts)
            Trace(volt_data, header)
            if self._config['plot'] == 'yes':
                # pylint: disable=no-member
                plt.plot(volt_data.tolist()[:-16])
                plt.show()

    def cleanup(self):
        """Free any resources used by card"""
        if self._config['plot'] == 'yes':
            plt.close('all')

# PRIVATE METHODS

    def _config_timebase(self, header):
        """Sets the capture clock"""
        sample_rate = getattr(ats, self._config['sample_rate'])
        header.sampling_rate = _sample_rate_to_hertz(sample_rate)
        self.setCaptureClock(getattr(ats, self._config['clock_source']),
                             sample_rate,
                             getattr(ats, self._config['clock_edge']),
                             self._config['decimation'])

    def _config_analog_inputs(self):
        """Specify the desired input range, termination, and coupling of an
        input channel
        """
        self._analog_inputs = []
        for input_data in self._config['analog_inputs']:
            analog_input = AnalogInput(getattr(ats, input_data['input_channel']),
                                       getattr(ats, input_data['input_coupling']),
                                       getattr(ats, input_data['input_range']),
                                       getattr(ats, input_data['input_impedance']))
            analog_input.initialize_on_board(self)
            self._analog_inputs.append(analog_input)

    def _config_trigger_system(self):
        """Configure each of the two trigger engines"""
        self.setTriggerOperation(getattr(ats, self._config['trigger_operation']),
                                 getattr(ats, self._config['trigger_engine_1']),
                                 getattr(ats, self._config['trigger_source_1']),
                                 getattr(ats, self._config['trigger_slope_1']),
                                 self._config['trigger_level_1'],
                                 getattr(ats, self._config['trigger_engine_2']),
                                 getattr(ats, self._config['trigger_source_2']),
                                 getattr(ats, self._config['trigger_slope_2']),
                                 self._config['trigger_level_2'])

    def _config_record(self, header):
        """Sets the record size and count on the card"""
        header.npts = (self._config['pre_trigger_samples']
                       + self._config['post_trigger_samples'])
        self.setRecordSize(self._config['pre_trigger_samples'],
                           self._config['post_trigger_samples'])
        self.setRecordCount(self._config['averages'])

    def _wait_for_trigger(self, timeout=30):
        """Wait for a trigger event until the timeout.

        This method will wait for a trigger event, but will eventually timeout.
        When this happens, it will either raise an error or force a trigger
        event, depending on the input.

        :param timeout: number of seconds to wait for a trigger event
        :type timeout: int

        :raises RuntimeError: if timeout occurs and force is set to False
        """
        if (self._config['trigger_source_1'] == 'TRIG_FORCE'
                or self._config['trigger_source_2'] == 'TRIG_FORCE'):
            self.forceTrigger()

        for _ in range(timeout):
            if not self.busy():
                break
            sleep(0.1)
        else:
            raise RuntimeError("Trigger event never occurred")

    def _read_to_record(self, channel):
        """Reads the last record from the card memory into the data buffer.

        :param channel: ATS constant associated with the desired input
        :type channel: int

        :returns: a single, averaged record
        :rtype: numpy.ndarray
        """
        pre_trig = self._config['pre_trigger_samples']
        post_trig = self._config['post_trigger_samples']
        samples = pre_trig + post_trig + 16
        averages = self._config['averages']
        data = np.zeros((averages, samples), ATSGeneric._data_type)
        for i in range(averages):
            # parameters
            record_num = i + 1 # 1-indexed
            transfer_offset = 0
            transfer_length = samples
            # read data from card
            self.read(channel,
                      data[i].ctypes.data_as(c_void_p),
                      ATSGeneric._bytes_per_sample,
                      record_num,
                      transfer_offset,
                      transfer_length)
        return data.mean(axis=0, dtype=int)

    def _convert_to_volts(self, data, max_volts):
        """Convert ATS data to voltages.

        Data is converted to voltages using the method described in the
        ATS-SDK-Guide.

        :param data: the values read from the ATS card
        :type data: numpy.ndarray

        :param max_volts: the max voltage for the input range
        :type max_volts: float

        :returns: voltages
        :rtype: numpy.ndarray

        :raises NotImplementedError: if bits per sample is out of range
        """
        _, c_bits = self.getChannelInfo()
        bits = c_bits.value
        if not 8 < bits <= 16:
            raise NotImplementedError("bits per sample must be between 9 and 16")
        bit_shift = 16 - bits
        midpoint = (1 << (bits - 1)) - 0.5
        convert_to_voltages = np.vectorize(
            lambda x: max_volts * ((x >> bit_shift) - midpoint) / midpoint,
            otypes=[np.float]
            )
        return convert_to_voltages(np.copy(data))

class AnalogInput:
    """An Alazar input configuration."""
    def __init__(self, channel, coupling, input_range, impedance):
        self._input_channel = channel
        self._input_coupling = coupling
        self._input_range = input_range
        self._input_impedance = impedance

    def get_input_channel(self):
        """Get the input channel for this input.

        :returns: the constant value of the input channel
        :rtype: int
        """
        return self._input_channel

    def get_input_range(self):
        """Get the input range for this input.

        :returns: the constant value of the input range
        :rtype: int
        """
        return self._input_range

    def initialize_on_board(self, board):
        """Initialize analog input on board.

        :param board: the ATS card to use
        :type board: ATSGeneric
        """
        board.inputControl(self._input_channel,
                           self._input_coupling,
                           self._input_range,
                           self._input_impedance)

class ATS660(ATSGeneric):
    """Subclass for ATS660"""
    pass

class ATS9440(ATSGeneric):
    """Subclass for ATS9440"""
    pass

# Private functions
def _input_range_to_volts(constant):
    """Translate input range constants

    :param constant: the ATS constant representing the input range
    :type constant: int

    :returns: maximum voltage for the given input range
    :rtype: float
    """
    return _INPUT_RANGE_TO_VOLTS[constant]

def _sample_rate_to_hertz(constant):
    """Translate sample rate constant to hertz.

    :param constant: the ATS constant representing the sample rate
    :type constant: int

    :returns: the sample rate, in hertz
    :rtype: int
    """
    return _SAMPLE_RATE_TO_HERTZ[constant]

_INPUT_RANGE_TO_VOLTS = {
    ats.INPUT_RANGE_PM_40_MV: 0.040,
    ats.INPUT_RANGE_PM_50_MV: 0.050,
    ats.INPUT_RANGE_PM_80_MV: 0.080,
    ats.INPUT_RANGE_PM_100_MV:0.100,
    ats.INPUT_RANGE_PM_125_MV:0.125,
    ats.INPUT_RANGE_PM_200_MV:0.200,
    ats.INPUT_RANGE_PM_250_MV:0.250,
    ats.INPUT_RANGE_PM_400_MV:0.400,
    ats.INPUT_RANGE_PM_500_MV:0.500,
    ats.INPUT_RANGE_PM_800_MV:0.800,
    ats.INPUT_RANGE_PM_1_V:   1.000,
    ats.INPUT_RANGE_PM_1_V_25:1.250,
    ats.INPUT_RANGE_PM_2_V:   2.000,
    ats.INPUT_RANGE_PM_2_V_5: 2.500,
    ats.INPUT_RANGE_PM_4_V:   4.000,
    ats.INPUT_RANGE_PM_5_V:   5.000,
    ats.INPUT_RANGE_PM_8_V:   8.000,
    ats.INPUT_RANGE_PM_10_V: 10.000,
    ats.INPUT_RANGE_PM_16_V: 16.000,
    ats.INPUT_RANGE_PM_20_V: 20.000,
    ats.INPUT_RANGE_PM_40_V: 40.000
    }

_SAMPLE_RATE_TO_HERTZ = {
    ats.SAMPLE_RATE_1KSPS:         1000,
    ats.SAMPLE_RATE_2KSPS:         2000,
    ats.SAMPLE_RATE_5KSPS:         5000,
    ats.SAMPLE_RATE_10KSPS:       10000,
    ats.SAMPLE_RATE_20KSPS:       20000,
    ats.SAMPLE_RATE_50KSPS:       50000,
    ats.SAMPLE_RATE_100KSPS:     100000,
    ats.SAMPLE_RATE_200KSPS:     200000,
    ats.SAMPLE_RATE_500KSPS:     500000,
    ats.SAMPLE_RATE_1MSPS:      1000000,
    ats.SAMPLE_RATE_2MSPS:      2000000,
    ats.SAMPLE_RATE_5MSPS:      5000000,
    ats.SAMPLE_RATE_10MSPS:    10000000,
    ats.SAMPLE_RATE_20MSPS:    20000000,
    ats.SAMPLE_RATE_25MSPS:    25000000,
    ats.SAMPLE_RATE_50MSPS:    50000000,
    ats.SAMPLE_RATE_100MSPS:  100000000,
    ats.SAMPLE_RATE_125MSPS:  125000000,
    ats.SAMPLE_RATE_160MSPS:  160000000,
    ats.SAMPLE_RATE_180MSPS:  180000000,
    ats.SAMPLE_RATE_200MSPS:  200000000,
    ats.SAMPLE_RATE_250MSPS:  250000000,
    ats.SAMPLE_RATE_400MSPS:  400000000,
    ats.SAMPLE_RATE_500MSPS:  500000000,
    ats.SAMPLE_RATE_800MSPS:  800000000,
    ats.SAMPLE_RATE_1000MSPS:1000000000,
    ats.SAMPLE_RATE_1200MSPS:1200000000,
    ats.SAMPLE_RATE_1500MSPS:1500000000,
    ats.SAMPLE_RATE_1600MSPS:1600000000,
    ats.SAMPLE_RATE_1800MSPS:1800000000,
    ats.SAMPLE_RATE_2000MSPS:2000000000,
    ats.SAMPLE_RATE_2400MSPS:2400000000,
    ats.SAMPLE_RATE_3000MSPS:3000000000,
    ats.SAMPLE_RATE_3600MSPS:3600000000,
    ats.SAMPLE_RATE_4000MSPS:4000000000,
    }