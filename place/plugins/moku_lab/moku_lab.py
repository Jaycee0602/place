"""The PLACE module for the Moku:Lab"""
import calendar
import time
from warnings import warn
import numpy as np
import matplotlib.pyplot as plt
#from matplotlib import cm
from place.plugins.instrument import Instrument
from place.config import PlaceConfig

try:
    from pymoku import Moku
    from pymoku.instruments import BodeAnalyzer
except ImportError:
    pass

MIN_P = 32
MAX_P = 512

def predictedsweeptime(a1, a2, s1, s2, n):
    """
    Empirical equation for sweep time estimateself.

    Note: rough estimate, lower freuqencies take longer (such as around 20kHz)
    """

    return max(a1*n, (a2/10000)*(n/3.75)) + max(s1*n, (s2/10000)*(n/3.75))

class MokuLab(Instrument):
    """The MokuLab class for place"""
    def __init__(self, config):
        """Initialize the MokuLab, without configuring.

        :param config: configuration data (as a parsed JSON object)
        :type config: dict
        """
        Instrument.__init__(self, config)
        self.total_updates = None
        self.ip_address = None
        #self.cs = None
        #self.my_cm = None
        self.time_safety_net = None
        self.sweeps = None
        self.axes = None
        self.m = None
        self.i = None


    def config(self, metadata, total_updates):

        self.total_updates = total_updates

        self.ip_address = PlaceConfig().get_config_value(self.__class__.__name__, 'ip_address')
        #self.cs = PlaceConfig().get_config_value(self.__class__.__name__, 'colour scheme')
        #self.my_cm = getattr(cm,self.cs)
        self.time_safety_net = float(PlaceConfig().get_config_value(
            self.__class__.__name__,
            'time_safety_net',
            '3.0'))

        wholepst = predictedsweeptime(
            self._config['averaging_time'],
            self._config['averaging_cycles'],
            self._config['settling_time'],
            self._config['settling_cycles'],
            self._config['data_points'])

        points = np.linspace(self._config['f_start'],self._config['f_end'],self._config['data_points'])
        points = points.tolist()

        sweeps = [points[x:x+MAX_P] for x in range(0,len(points),MAX_P)]

        if len(sweeps[-1]) < MIN_P:
            sweeps[-1] = sweeps[-2][-MIN_P:] + sweeps[-1]
            sweeps[-2] = sweeps[-2][:-MIN_P]

        self.sweeps = sweeps

        safe_wholepst = wholepst * self.time_safety_net
        #print('Each {} update is predicted to take {:.2f} seconds'.format(
            #self.__class__.__name__, wholepst))
        #print('PLACE {} will wait for {:.2f} seconds'.format(
            #self.__class__.__name__, safe_wholepst))

        metadata['MokuLab-predicted-sweep-time'] = wholepst
        metadata['MokuLab-safe-predicted-sweep-time'] = safe_wholepst

        if self._config['plot']:
            self.axes = [None, None]
            if self._config['channel'] != 'ch2':
                ch1_fig, self.axes[0] = plt.subplots(2, 2)
                ch1_fig.canvas.set_window_title(self.__class__.__name__ + '-Channel 1')

                self._plot_fig(self.axes[0][0][0], self.axes[0][1][0], 'Magnitude (dB)', 1)

            if self._config['channel'] != 'ch1':
                ch2_fig, (self.axes[1]) = plt.subplots(2, 2)
                ch2_fig.canvas.set_window_title(self.__class__.__name__ + '-Channel 2')

                self._plot_fig(self.axes[1][0][1], self.axes[1][1][1], 'Phase (Cycles)', 2)

            plt.ion()
            plt.show()


    def update(self, update_number):
        totals = {'freq': [], 'mag': [[], []], 'phase': [[], []]}
        for sweep in self.sweeps:
            lines = None
            if self._config['plot']:
                lines = self._plot_empty_lines()
            totals = self._sweep(sweep, totals, lines)
        x = totals['freq']
        m1, m2 = totals['mag']
        p1, p2 = totals['phase']

        magnitude_dB_ch1 = np.array(
            [[x[i], m1[i]] for i in range(min(len(x), len(m1)))])
        magnitude_dB_ch2 = np.array(
            [[x[i], m2[i]] for i in range(min(len(x), len(m2)))])

        phase_ch1 = np.array(
            [[x[i], p1[i]] for i in range(min(len(x), len(p1)))])
        phase_ch2 = np.array(
            [[x[i], p2[i]] for i in range(min(len(x), len(p2)))])

        magnitude_dB_ch1_field = '{}-magnitude_dB_ch1'.format(self.__class__.__name__)
        phase_ch1_field = '{}-phase_ch1'.format(self.__class__.__name__)

        magnitude_dB_ch2_field = '{}-magnitude_dB_ch2'.format(self.__class__.__name__)
        phase_ch2_field = '{}-phase_ch2'.format(self.__class__.__name__)

        shape = '({},2)float64'.format(self._config['data_points'])

        data = np.array(
            [(magnitude_dB_ch1, phase_ch1, magnitude_dB_ch2, phase_ch2)],
            dtype=[(magnitude_dB_ch1_field, shape), (phase_ch1_field, shape),
                   (magnitude_dB_ch2_field, shape), (phase_ch2_field, shape)])

        framedata = {"frequency_kHz": np.array(totals['freq']).copy(),
                     "magnitude_dB_ch1": np.array(totals['mag'][0]).copy(),
                     "phase_ch1": np.array(totals['phase'][0]).copy(),
                     "magnitude_dB_ch2": np.array(totals['mag'][1]).copy(),
                     "phase_ch2": np.array(totals['phase'][1]).copy()}

        if self._config['plot']:
            # TODO: make this take 'totals' instead of 'framedata'
            self._wiggle_plot(update_number, framedata)

        if update_number == self.total_updates - 2:
            print('Almost there, I have {} more update to work through.'.format(
                self.total_updates - (update_number + 1)))
            if self._config['pause']:
                print('Go ahead and close the figure would you?')
                print('Cheers mate.')
        elif update_number == self.total_updates - 1:
            print('I\'ve finished the final sweep.')
            if self._config['pause']:
                print('Please close the plot to wrap up your experiment.')
            print('May the odds be ever in your favor.')

        else:
            print('Don\'t celebrate yet,')
            print('I have {} more updates to work through.'.format(
                self.total_updates - (update_number + 1)))
            if self._config['pause']:
                print('I need you to close the figure so I can continue,')
                print('cheers mate.')

        if self._config['plot']:
            if self._config['pause']:
                plt.ioff()
                plt.show() # pause
                plt.ion()
            else:
                plt.draw()
                plt.pause(0.001)

        return data.copy()

    def cleanup(self, abort=False):
        if abort is False and self._config['plot']:
            plt.ioff()
            print('...please close the {} plot to continue...'.format(self.__class__.__name__))
            plt.show()

    def _sweep_setup(self, sweep):
        self.m = Moku(self.ip_address)
        self.i = self.m.deploy_or_connect(BodeAnalyzer)
        try:
            self.i.set_framerate(5)
            if self._config['plotting_type'] == 'live':
                self.i.set_xmode('sweep')
            else:
                self.i.set_xmode('fullframe')
            self.i.set_output(1, self._config['ch1_amp'])
            self.i.set_output(2, self._config['ch2_amp'])
            self.i.set_frontend(channel=1, ac=True, atten=False, fiftyr=True)
            self.i.set_frontend(channel=2, ac=True)
        except:
            self.m.close()
            raise
        pst = predictedsweeptime(
            self._config['averaging_time'],
            self._config['averaging_cycles'],
            self._config['settling_time'],
            self._config['settling_cycles'],
            len(sweep))
        self.i.set_sweep(
            sweep[0] * 1000,
            sweep[-1] * 1000,
            len(sweep),
            False,
            self._config['averaging_time'],
            self._config['settling_time'],
            self._config['averaging_cycles'],
            self._config['settling_cycles'])
        self.i.start_sweep(single=self._config['single_sweep'])
        return pst


    def _sweep_cleanup(self, curr, totals):
        totals['mag'][0].extend(curr['mag'][0])
        totals['phase'][0].extend(curr['phase'][0])
        totals['mag'][1].extend(curr['mag'][1])
        totals['phase'][1].extend(curr['phase'][1])
        totals['freq'].extend((np.array(curr['freq'])/1000).tolist())
        self.m.close()
        return totals


    def _sweep(self, sweep, totals, lines=None):
        pst = self._sweep_setup(sweep)
        curr = {'freq': [], 'mag': ([], []), 'phase': ([], [])}
        then = calendar.timegm(time.gmtime())
        now = 0
        frame = self.i.get_realtime_data()
        curr['freq'] = frame.frequency
        while now - then < pst*self.time_safety_net:
            curr['mag'] = ([np.nan if x is None else x for x in frame.ch1.magnitude_dB],
                           [np.nan if x is None else x for x in frame.ch2.magnitude_dB])
            curr['phase'] = ([np.nan if x is None else x for x in frame.ch1.phase],
                             [np.nan if x is None else x for x in frame.ch2.phase])
            if lines and self._config['plotting_type'] == 'live':
                if self._config['channel'] != 'ch2':
                    self._plot_sweep(0, lines, curr, totals)
                if self._config['channel'] != 'ch1':
                    self._plot_sweep(1, lines, curr, totals)
            if self._config['channel'] == 'ch1' and curr['mag'][0][-1] is not np.nan:
                break
            elif self._config['channel'] == 'ch2' and curr['mag'][1][-1] is not np.nan:
                break
            elif (self._config['channel'] == 'both'
                  and curr['mag'][0][-1] is not np.nan
                  and curr['mag'][1][-1] is not np.nan):
                break
            now = calendar.timegm(time.gmtime())
            frame = self.i.get_realtime_data()
        return self._sweep_cleanup(curr, totals)


    def _plot_sweep(self, channel, lines, curr, totals):
        ax00 = self.axes[channel][0][0]
        ax01 = self.axes[channel][0][1]
        ch1_mag_line, ch1_phase_line = lines[channel]
        ch1_mag_line.set_ydata(totals['mag'][channel] + curr['mag'][channel])
        ch1_mag_line.set_xdata(
            totals['freq'] + (np.array(curr['freq'])/1000).tolist())
        ch1_phase_line.set_ydata(totals['phase'][channel] + curr['phase'][channel])
        ch1_phase_line.set_xdata(
            totals['freq'] + (np.array(curr['freq'])/1000).tolist())
        ax00.set_xlim(self._config['f_start'], self._config['f_end'])
        ax00.relim()
        ax00.autoscale_view()
        ax01.set_xlim(self._config['f_start'], self._config['f_end'])
        ax01.relim()
        ax01.autoscale_view()
        plt.draw()
        plt.pause(0.001)


    def _plot_empty_lines(self):
        """Set up the empty plot lines during the update phase"""
        ch1_lines = self._plot_empty_lines_ch(0)
        ch2_lines = self._plot_empty_lines_ch(1)
        return [ch1_lines, ch2_lines]


    def _plot_empty_lines_ch(self, channel):
        """Return emply lines for the given channel.

        For channel 1, use 0.
        For channel 2, use 1.
        """
        ax00 = self.axes[channel][0][0]
        ax01 = self.axes[channel][0][1]
        if self._config['channel'] != 'ch{}'.format(channel):
            mag_line, = ax00.plot([])
            phase_line, = ax01.plot([])
            return mag_line, phase_line
        return None, None


    def _plot_fig(self, curr_plot, wiggle_plot, measured, x):
        """
        Setting up figures and subplots.
        curr_plot: self.axes[0][]
        wiggle_plot: self.axes[1][]
        measured (y label of top plot): 'Magnitude (dB)' or 'Phase (Cycles)'
        x (Channel number): 1 or 2
        """

        f_start = self._config['f_start']
        f_end = self._config['f_end']

        ax0 = curr_plot
        ax1 = wiggle_plot

        ax0.set_xlabel('Frequency (kHz)')
        ax0.set_ylabel(measured)
        ax0.set_title('Channel {} Frequency Spectrum {} - {} kHz'.format(x, f_start, f_end))

        ax1.set_xlim((-1, self.total_updates))
        ax1.set_xlabel('Update Number')
        ax1.set_ylim(f_start, f_end)
        ax1.set_ylabel('Frequency (kHz)')
        ax1.set_title('Channel {} Frequency Sectra {} - {} kHz'.format(x, f_start, f_end))

    def _wiggle_plot(self, number, framedata):
        """Plot the data as a wiggle plot.

        :param number: the update number
        :type number: int

        :param frequency_kH: the frequency to plot along axis
        :type frequency_kH: numpy.array

        :param magnitude_dB: the magnitude to plot
        :type magnitude_dB: numpy.array

        :param phase: the phase to plot
        :type phase: numpy.array

        Plots using standard matplotlib backend.
        """

        frequency_kHz = framedata["frequency_kHz"]
        magnitude_dB_ch1 = framedata["magnitude_dB_ch1"]
        phase_ch1 = framedata["phase_ch1"]
        magnitude_dB_ch2 = framedata["magnitude_dB_ch2"]
        phase_ch2 = framedata["phase_ch2"]

        def plot_final_update(axes, mp):
            """
            Plots subplots when figure only shown at the end of updates.
            axes: self.axes[][]
            mp: magnitude_dB_chx or phase_chx

            """
            ax = axes

            ax.plot(frequency_kHz, mp) #color = self.my_cm(number))
            ax.set_xlim(self._config['f_start'], self._config['f_end'])
            ax.relim()
            ax.autoscale_view()

            plt.draw()
            plt.pause(0.001)

        def plot_wiggles(axes, measurement):
            """
            Plots wiggle plots.
            axes: self.axes[][]
            measurement: avg_mag_chx or phase_chx
            """
            ax = axes

            data = measurement / np.amax(np.abs(measurement)) + number
            ax.plot(data, frequency_kHz, color='black', linewidth=0.5)
            ax.fill_betweenx(
                frequency_kHz,
                data,
                number,
                where=[False if np.isnan(x) else x > number for x in data],
                color='black')
            plt.draw()
            plt.pause(0.001)

        if self._config['plotting_type'] == 'update':

            if self._config['channel'] != 'ch2':
                plot_final_update((self.axes[0])[0][0], magnitude_dB_ch1)
                plot_final_update((self.axes[0])[0][1], phase_ch1)

            if self._config['channel'] != 'ch1':
                plot_final_update((self.axes[1])[0][0], magnitude_dB_ch2)
                plot_final_update((self.axes[1])[0][1], phase_ch2)

            if self._config['pause']:
                plt.ioff()
                plt.show() # pause
                plt.ion()
            else:
                plt.draw()
                plt.pause(0.001)

        if self._config['channel'] != 'ch2':
            try:
                avg_mag_ch1 = magnitude_dB_ch1 - np.average(magnitude_dB_ch1)
            except TypeError:
                warn("Detected a 'None' value in the data - attempting to remove...")
                print(magnitude_dB_ch1)
                if magnitude_dB_ch1[-1] is None or phase_ch1[-1] is None:
                    frequency_kHz = frequency_kHz[:-1]
                    magnitude_dB_ch1 = magnitude_dB_ch1[:-1]
                    phase_ch1 = phase_ch1[:-1]
                avg_mag_ch1 = magnitude_dB_ch1 - np.average(magnitude_dB_ch1)

            plot_wiggles((self.axes[0])[1][0], avg_mag_ch1)
            plot_wiggles((self.axes[0])[1][1], phase_ch1)

        if self._config['channel'] != 'ch1':
            try:
                avg_mag_ch2 = magnitude_dB_ch2 - np.average(magnitude_dB_ch2)
            except TypeError:
                warn("Detected a 'None' value in the data - attempting to remove...")
                print(magnitude_dB_ch2)
                if magnitude_dB_ch2[-1] is None or phase_ch2[-1] is None:
                    frequency_kHz = frequency_kHz[:-1]
                    magnitude_dB_ch2 = magnitude_dB_ch2[:-1]
                    phase_ch2 = phase_ch2[:-1]
                avg_mag_ch2 = magnitude_dB_ch2 - np.average(magnitude_dB_ch2)

            plot_wiggles((self.axes[1])[1][0], avg_mag_ch2)
            plot_wiggles((self.axes[1])[1][1], phase_ch2)
