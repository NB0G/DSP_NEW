from scipy.fft import fftshift, irfft, rfftfreq

from filters.equalizer_bands import EQUALIZER_BANDS
from util import (
    StreamingFirFilter,
    build_hamming_window,
    db_to_gain,
    make_odd,
)


SINC_BANDS = EQUALIZER_BANDS
DEFAULT_TAP_COUNT = 2049
DEFAULT_FFT_SIZE = 8192


class HammingSincFilterBank:
    def __init__(
        self,
        sample_rate,
        band_gains_db,
        tap_count=DEFAULT_TAP_COUNT,
        fft_size=DEFAULT_FFT_SIZE,
    ):
        self.sample_rate = sample_rate
        self.tap_count = make_odd(tap_count)
        self.fft_size = max(fft_size, self.tap_count * 4)
        self.band_gains_db = band_gains_db.copy()
        self.band_gains = {}

        for band_number, gain_db in self.band_gains_db.items():
            self.band_gains[band_number] = db_to_gain(gain_db)

        self.filter = StreamingFirFilter([0] * self.tap_count)
        self.rebuild_kernel()

    def set_band_gain(self, band_number, gain_db):
        self.band_gains_db[band_number] = gain_db
        self.band_gains[band_number] = db_to_gain(gain_db)
        self.rebuild_kernel()

    def rebuild_kernel(self):
        frequencies = rfftfreq(self.fft_size, 1 / self.sample_rate)
        frequency_response = [
            self.band_gain_for_frequency(frequency_hz)
            for frequency_hz in frequencies
        ]
        impulse_response = fftshift(irfft(frequency_response, self.fft_size)).tolist()
        center = len(impulse_response) // 2
        half_taps = self.tap_count // 2
        kernel = impulse_response[center - half_taps:center + half_taps + 1]
        window = build_hamming_window(len(kernel))

        self.filter.kernel = [
            kernel_value * window_value
            for kernel_value, window_value in zip(kernel, window)
        ]
        self.filter.kernel_fft_by_size = {}

    def band_gain_for_frequency(self, frequency_hz):
        nyquist_hz = self.sample_rate / 2

        for band_index, (low_cutoff_hz, high_cutoff_hz) in enumerate(
            SINC_BANDS,
            start=1,
        ):
            high_cutoff_hz = min(high_cutoff_hz, nyquist_hz)
            is_last_band = band_index == len(SINC_BANDS)

            if low_cutoff_hz <= frequency_hz < high_cutoff_hz:
                return self.band_gains[band_index]

            if is_last_band and low_cutoff_hz <= frequency_hz <= nyquist_hz:
                return self.band_gains[band_index]

        return 0

    def process_samples(self, samples):
        return self.filter.process_samples(samples)
