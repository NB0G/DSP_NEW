import numpy as np
from scipy.signal import cheby2, sosfilt

from filters.equalizer_bands import EQUALIZER_BANDS
from util import db_to_gain


CHEBYSHEV_BANDS = []
for band_index, (low_cutoff_hz, high_cutoff_hz) in enumerate(EQUALIZER_BANDS):
    if band_index == 0:
        filter_type = "low_pass"
    elif band_index == len(EQUALIZER_BANDS) - 1:
        filter_type = "high_pass"
    else:
        filter_type = "band_pass"

    CHEBYSHEV_BANDS.append((filter_type, low_cutoff_hz, high_cutoff_hz))
DEFAULT_ORDER = 4
DEFAULT_STOPBAND_ATTENUATION_DB = 40
NYQUIST_MARGIN = 0.99


class StreamingSosFilter:
    def __init__(self, sos, gain_db=0):
        self.sos = sos
        self.zi = np.zeros((len(sos), 2))
        self.set_gain_db(gain_db)

    def set_gain_db(self, gain_db):
        self.gain_db = gain_db
        self.gain = db_to_gain(gain_db)

    def process_samples(self, samples):
        samples = list(samples)
        if not samples:
            return []

        filtered_samples, self.zi = sosfilt(self.sos, samples, zi=self.zi)

        return (filtered_samples * self.gain).tolist()


class ChebyshevFilterBank:
    def __init__(
        self,
        sample_rate,
        band_gains_db,
        order=DEFAULT_ORDER,
        stopband_attenuation_db=DEFAULT_STOPBAND_ATTENUATION_DB,
    ):
        self.sample_rate = sample_rate
        self.order = order
        self.stopband_attenuation_db = stopband_attenuation_db
        self.band_gains_db = band_gains_db.copy()
        self.filters_by_band = {}

        self.build_filters()

    def build_filters(self):
        nyquist_hz = self.sample_rate / 2

        for band_number, (filter_type, low_cutoff_hz, high_cutoff_hz) in enumerate(
            CHEBYSHEV_BANDS,
            start=1,
        ):
            sos = self.build_band_sos(
                filter_type,
                low_cutoff_hz,
                high_cutoff_hz,
                nyquist_hz,
            )

            if sos is None:
                continue

            gain_db = self.band_gains_db.get(band_number, 0)
            self.filters_by_band[band_number] = StreamingSosFilter(sos, gain_db)

    def build_band_sos(
        self,
        filter_type,
        low_cutoff_hz,
        high_cutoff_hz,
        nyquist_hz,
    ):
        max_cutoff_hz = nyquist_hz * NYQUIST_MARGIN

        if filter_type == "low_pass":
            cutoff_hz = min(high_cutoff_hz, max_cutoff_hz)
            if cutoff_hz <= 0:
                return None

            return cheby2(
                self.order,
                self.stopband_attenuation_db,
                cutoff_hz,
                btype="lowpass",
                fs=self.sample_rate,
                output="sos",
            )

        if filter_type == "high_pass":
            cutoff_hz = min(low_cutoff_hz, max_cutoff_hz)
            if cutoff_hz <= 0 or cutoff_hz >= max_cutoff_hz:
                return None

            return cheby2(
                self.order,
                self.stopband_attenuation_db,
                cutoff_hz,
                btype="highpass",
                fs=self.sample_rate,
                output="sos",
            )

        high_cutoff_hz = min(high_cutoff_hz, max_cutoff_hz)
        if low_cutoff_hz <= 0 or low_cutoff_hz >= high_cutoff_hz:
            return None

        return cheby2(
            self.order,
            self.stopband_attenuation_db,
            [low_cutoff_hz, high_cutoff_hz],
            btype="bandpass",
            fs=self.sample_rate,
            output="sos",
        )

    def set_band_gain(self, band_number, gain_db):
        self.band_gains_db[band_number] = gain_db

        audio_filter = self.filters_by_band.get(band_number)
        if audio_filter is not None:
            audio_filter.set_gain_db(gain_db)

    def process_samples(self, samples):
        samples = list(samples)
        if not samples:
            return []

        mixed_samples = [0.0] * len(samples)

        for audio_filter in self.filters_by_band.values():
            filtered_samples = audio_filter.process_samples(samples)

            for index, sample in enumerate(filtered_samples):
                mixed_samples[index] += sample

        return mixed_samples
