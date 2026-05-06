import time
import wave
from array import array
from threading import Thread

from buffers.dual_thread_ring_buffer import RingBufferDualThread
from buffers.shifting_buffer import ShiftingBuffer
from buffers.single_thread_ring_buffer import SingleThreadRingBuffer
from filters.chebyshev.chebyshev_filter_bank import ChebyshevFilterBank
from filters.chebyshev_window.chebyshev_window_filter_bank import (
    ChebyshevWindowFirFilterBank,
    DEFAULT_TAP_COUNT,
)


DEFAULT_BLOCK_SIZE = 64
DEFAULT_RING_BUFFER_SIZE_BYTES = 32
DUAL_THREAD_INPUT_FRAMES_PER_CYCLE = 2
SINGLE_THREAD_INPUT_FRAMES_PER_CYCLE = 8
RING_BUFFER_OUTPUT_FRAMES_PER_CYCLE = 1
SAMPLE_READ_TIMEOUT_SECONDS = 0.01
DEFAULT_ECHO_DELAY_MS = 220
DEFAULT_ECHO_FEEDBACK = 0.35
DEFAULT_ECHO_WET = 0.4
DEFAULT_CLIPPING_THRESHOLD = 1200
BUFFER_MODE_DUAL_THREAD = "dual_thread"
BUFFER_MODE_SINGLE_THREAD = "single_thread"
BUFFER_MODE_SHIFTING = "shifting"
FILTER_TYPE_CHEBYSHEV = "chebyshev_iir"
FILTER_TYPE_CHEBYSHEV_WINDOW_FIR = "chebyshev_window_fir"
FILTER_TYPE_SINC = FILTER_TYPE_CHEBYSHEV_WINDOW_FIR
OUTPUT_CHANNELS = 1
BYTES_PER_SAMPLE = 2
DEFAULT_BAND_GAINS_DB = {
    1: 0,
    2: 0,
    3: 0,
    4: 0,
    5: 0,
    6: 0,
}


def require_pyaudio():
    try:
        import pyaudio
    except ImportError as error:
        raise RuntimeError(
            "PyAudio не установлен. Установите PortAudio и PyAudio для воспроизведения."
        ) from error

    return pyaudio


def clamp_int16(value):
    return max(-32768, min(32767, int(value)))


def stereo_to_mono(samples):
    mono_samples = []

    for index in range(0, len(samples) - 1, 2):
        left = samples[index]
        right = samples[index + 1]
        mono_samples.append((left + right) / 2)

    return mono_samples


def bytes_to_samples(frames, channels):
    samples = array("h")
    samples.frombytes(frames)

    if channels == 2:
        return stereo_to_mono(samples)

    return samples


def samples_to_bytes(samples):
    pcm = array("h")

    for sample in samples:
        pcm.append(clamp_int16(sample))

    return pcm.tobytes()


def sample_to_bytes(sample):
    pcm = array("h", [clamp_int16(sample)])
    return pcm.tobytes()


def build_chebyshev_window_fir_filter_bank(sample_rate, taps, band_gains_db=None):
    gains = DEFAULT_BAND_GAINS_DB.copy()
    if band_gains_db is not None:
        gains.update(band_gains_db)

    return ChebyshevWindowFirFilterBank(sample_rate, gains, taps)


def build_chebyshev_filter_bank(sample_rate, band_gains_db=None):
    gains = DEFAULT_BAND_GAINS_DB.copy()
    if band_gains_db is not None:
        gains.update(band_gains_db)

    return ChebyshevFilterBank(sample_rate, gains)


def build_filter_bank(
    sample_rate,
    taps,
    band_gains_db=None,
    filter_type=FILTER_TYPE_CHEBYSHEV,
):
    if filter_type == FILTER_TYPE_CHEBYSHEV:
        return build_chebyshev_filter_bank(sample_rate, band_gains_db)

    return build_chebyshev_window_fir_filter_bank(sample_rate, taps, band_gains_db)


def mix_filter_outputs(filter_outputs):
    mixed_samples = []

    for samples_at_time in zip(*filter_outputs):
        mixed_samples.append(sum(samples_at_time))

    return mixed_samples


def process_samples_with_filter_bank(samples, filters):
    if hasattr(filters, "process_samples"):
        return filters.process_samples(samples)

    filter_outputs = []

    for audio_filter in filters:
        filter_outputs.append(audio_filter.process_samples(samples))

    return mix_filter_outputs(filter_outputs)


def clip_samples(samples, threshold=DEFAULT_CLIPPING_THRESHOLD):
    return [max(-threshold, min(threshold, sample)) for sample in samples]


class EchoEffect:
    def __init__(
        self,
        sample_rate,
        delay_ms=DEFAULT_ECHO_DELAY_MS,
        feedback=DEFAULT_ECHO_FEEDBACK,
        wet=DEFAULT_ECHO_WET,
    ):
        delay_samples = max(1, int(sample_rate * delay_ms / 1000))
        self.buffer = [0.0] * delay_samples
        self.index = 0
        self.feedback = feedback
        self.wet = wet

    def process_samples(self, samples):
        processed_samples = []

        for sample in samples:
            delayed_sample = self.buffer[self.index]
            output_sample = sample + delayed_sample * self.wet
            self.buffer[self.index] = sample + delayed_sample * self.feedback
            self.index = (self.index + 1) % len(self.buffer)
            processed_samples.append(output_sample)

        return processed_samples


ReverbEffect = EchoEffect


class EqualizerPlayer:
    def __init__(
        self,
        file_path,
        buffer_mode=BUFFER_MODE_DUAL_THREAD,
        filter_type=FILTER_TYPE_CHEBYSHEV,
        taps=DEFAULT_TAP_COUNT,
        ring_buffer_size_bytes=DEFAULT_RING_BUFFER_SIZE_BYTES,
        band_gains_db=None,
        echo_enabled=False,
        clipping_enabled=False,
        reverb_enabled=None,
    ):
        self.file_path = file_path
        self.buffer_mode = buffer_mode
        self.filter_type = filter_type
        self.taps = taps
        self.block_size = DEFAULT_BLOCK_SIZE
        self.ring_buffer_size_bytes = ring_buffer_size_bytes
        self.band_gains_db = DEFAULT_BAND_GAINS_DB.copy()
        self.filters = []
        self.echo = None
        self.ring_buffer = None
        self.stopped = False
        self.echo_enabled = echo_enabled if reverb_enabled is None else reverb_enabled
        self.clipping_enabled = clipping_enabled

        if band_gains_db is not None:
            self.band_gains_db.update(band_gains_db)

    def set_band_gain(self, band_number, gain_db):
        self.band_gains_db[band_number] = gain_db

        if self.filters:
            if hasattr(self.filters, "set_band_gain"):
                self.filters.set_band_gain(band_number, gain_db)
            else:
                self.filters[band_number - 1].set_gain_db(gain_db)

    def set_echo_enabled(self, enabled):
        self.echo_enabled = enabled

    def set_reverb_enabled(self, enabled):
        self.set_echo_enabled(enabled)

    def set_clipping_enabled(self, enabled):
        self.clipping_enabled = enabled

    def stop(self):
        self.stopped = True

        if self.ring_buffer is not None:
            self.ring_buffer.close()

    def play(self):
        if self.buffer_mode == BUFFER_MODE_SHIFTING:
            self.play_shifting_buffer()
        elif self.buffer_mode == BUFFER_MODE_SINGLE_THREAD:
            self.play_single_thread()
        else:
            self.play_dual_thread()

    def build_filters(self, sample_rate):
        self.filters = build_filter_bank(
            sample_rate,
            self.taps,
            self.band_gains_db,
            self.filter_type,
        )
        self.echo = EchoEffect(sample_rate)

    def process_audio_samples(self, samples):
        processed_samples = process_samples_with_filter_bank(samples, self.filters)

        if self.echo_enabled:
            processed_samples = self.echo.process_samples(processed_samples)

        if self.clipping_enabled:
            processed_samples = clip_samples(processed_samples)

        return processed_samples

    def write_filtered_audio_to_buffer_dual_thread(self, wav_file):
        channels = wav_file.getnchannels()
        bytes_per_write = min(
            DUAL_THREAD_INPUT_FRAMES_PER_CYCLE * BYTES_PER_SAMPLE,
            max(BYTES_PER_SAMPLE, self.ring_buffer.capacity // 2),
        )
        prefetch_bytes = max(
            self.ring_buffer.capacity,
            DEFAULT_BLOCK_SIZE * OUTPUT_CHANNELS * BYTES_PER_SAMPLE,
        )
        pending = bytearray()
        wav_has_data = True

        def read_filtered_bytes(frames_to_read):
            frames = wav_file.readframes(frames_to_read)
            if not frames:
                return b""

            samples = bytes_to_samples(frames, channels)
            filtered_samples = self.process_audio_samples(samples)
            return samples_to_bytes(filtered_samples)

        while not self.stopped:
            while wav_has_data and len(pending) < prefetch_bytes and not self.stopped:
                filtered_bytes = read_filtered_bytes(DEFAULT_BLOCK_SIZE)
                if not filtered_bytes:
                    wav_has_data = False
                    break

                pending += filtered_bytes

            if not pending:
                break

            required_space = min(bytes_per_write, len(pending))
            free_space = self.ring_buffer.wait_for_free_space(required_space)
            if free_space < BYTES_PER_SAMPLE:
                break

            bytes_to_write = min(len(pending), free_space)
            bytes_to_write -= bytes_to_write % BYTES_PER_SAMPLE
            if bytes_to_write == 0:
                break

            self.ring_buffer.write(pending[:bytes_to_write])
            del pending[:bytes_to_write]

        self.ring_buffer.close()

    def play_dual_thread(self):
        wav_file = wave.open(self.file_path, "rb")
        sample_rate = wav_file.getframerate()
        self.build_filters(sample_rate)
        pyaudio = require_pyaudio()

        self.ring_buffer = RingBufferDualThread(self.ring_buffer_size_bytes)

        producer = Thread(
            target=self.write_filtered_audio_to_buffer_dual_thread,
            args=(wav_file,),
        )
        producer.start()

        def play_from_ring_buffer(in_data, frame_count, time_info, status_flags):
            data = bytearray()
            finished = False

            for _frame_index in range(frame_count * OUTPUT_CHANNELS):
                sample_data, finished = self.ring_buffer.read_sample(
                    SAMPLE_READ_TIMEOUT_SECONDS
                )
                data += sample_data

                if finished or self.stopped:
                    break

            bytes_needed = frame_count * OUTPUT_CHANNELS * BYTES_PER_SAMPLE
            if len(data) < bytes_needed:
                data += bytes(bytes_needed - len(data))

            if finished or self.stopped:
                return bytes(data), pyaudio.paComplete

            return bytes(data), pyaudio.paContinue

        audio = pyaudio.PyAudio()
        stream = audio.open(
            format=pyaudio.paInt16,
            channels=OUTPUT_CHANNELS,
            rate=sample_rate,
            output=True,
            frames_per_buffer=RING_BUFFER_OUTPUT_FRAMES_PER_CYCLE,
            stream_callback=play_from_ring_buffer,
            start=False,
        )

        stream.start_stream()

        while stream.is_active() and not self.stopped:
            time.sleep(0.05)

        self.stop()
        stream.stop_stream()
        stream.close()
        audio.terminate()
        producer.join()
        wav_file.close()

    def play_single_thread(self):
        wav_file = wave.open(self.file_path, "rb")
        channels = wav_file.getnchannels()
        sample_rate = wav_file.getframerate()
        self.build_filters(sample_rate)
        pyaudio = require_pyaudio()

        self.ring_buffer = SingleThreadRingBuffer(self.ring_buffer_size_bytes)

        audio = pyaudio.PyAudio()
        stream = audio.open(
            format=pyaudio.paInt16,
            channels=OUTPUT_CHANNELS,
            rate=sample_rate,
            output=True,
            frames_per_buffer=RING_BUFFER_OUTPUT_FRAMES_PER_CYCLE,
        )

        def write_next_frames_to_buffer(frames_to_read):
            frames = wav_file.readframes(frames_to_read)
            if not frames:
                return False

            samples = bytes_to_samples(frames, channels)
            filtered_samples = self.process_audio_samples(samples)

            for sample in filtered_samples:
                if self.ring_buffer.free_space() < BYTES_PER_SAMPLE:
                    break

                self.ring_buffer.write(sample_to_bytes(sample))

                if self.stopped:
                    break

            return True

        wav_has_data = True
        while self.ring_buffer.free_space() >= BYTES_PER_SAMPLE and not self.stopped:
            frames_to_read = self.ring_buffer.free_space() // BYTES_PER_SAMPLE
            wav_has_data = write_next_frames_to_buffer(frames_to_read)
            if not wav_has_data:
                break

        bytes_per_cycle = SINGLE_THREAD_INPUT_FRAMES_PER_CYCLE * BYTES_PER_SAMPLE
        while self.ring_buffer.available() > 0 and not self.stopped:
            sample_data, finished = self.ring_buffer.read_sample()
            stream.write(sample_data)

            if wav_has_data and self.ring_buffer.free_space() >= bytes_per_cycle:
                wav_has_data = write_next_frames_to_buffer(
                    SINGLE_THREAD_INPUT_FRAMES_PER_CYCLE
                )

            if finished:
                break

        self.ring_buffer.close()

        while self.ring_buffer.available() > 0 and not self.stopped:
            sample_data, finished = self.ring_buffer.read_sample()
            stream.write(sample_data)

            if finished:
                break

        stream.stop_stream()
        stream.close()
        audio.terminate()
        wav_file.close()

    def play_shifting_buffer(self):
        wav_file = wave.open(self.file_path, "rb")
        channels = wav_file.getnchannels()
        input_bytes_per_frame = channels * wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        self.build_filters(sample_rate)
        pyaudio = require_pyaudio()

        self.ring_buffer = ShiftingBuffer(self.ring_buffer_size_bytes)
        input_frames_per_chunk = max(
            1,
            self.ring_buffer.part_capacity // input_bytes_per_frame,
        )
        output_bytes_per_chunk = self.ring_buffer.part_capacity
        output_frames_per_buffer = max(
            1,
            output_bytes_per_chunk // (OUTPUT_CHANNELS * BYTES_PER_SAMPLE),
        )

        audio = pyaudio.PyAudio()
        stream = audio.open(
            format=pyaudio.paInt16,
            channels=OUTPUT_CHANNELS,
            rate=sample_rate,
            output=True,
            frames_per_buffer=output_frames_per_buffer,
        )

        frames = wav_file.readframes(input_frames_per_chunk)
        while frames and not self.stopped:
            samples = bytes_to_samples(frames, channels)
            filtered_samples = self.process_audio_samples(samples)

            for sample in filtered_samples:
                self.ring_buffer.write(sample_to_bytes(sample))

                if self.ring_buffer.available() >= output_bytes_per_chunk:
                    data, finished = self.ring_buffer.read(output_bytes_per_chunk)
                    stream.write(data)

                    if finished or self.stopped:
                        break

            frames = wav_file.readframes(input_frames_per_chunk)

        self.ring_buffer.close()

        while self.ring_buffer.available() > 0 and not self.stopped:
            data, finished = self.ring_buffer.read(output_bytes_per_chunk)

            if not data:
                break

            stream.write(data)

            if finished:
                break

        stream.stop_stream()
        stream.close()
        audio.terminate()
        wav_file.close()


def play_wav_with_filter_dual_thread(
    file_path,
    taps=DEFAULT_TAP_COUNT,
    band_gains_db=None,
    ring_buffer_size_bytes=DEFAULT_RING_BUFFER_SIZE_BYTES,
    filter_type=FILTER_TYPE_CHEBYSHEV,
    echo_enabled=False,
    clipping_enabled=False,
    reverb_enabled=None,
):
    player = EqualizerPlayer(
        file_path,
        BUFFER_MODE_DUAL_THREAD,
        filter_type,
        taps,
        ring_buffer_size_bytes,
        band_gains_db,
        echo_enabled,
        clipping_enabled,
        reverb_enabled,
    )
    player.play()


def play_wav_with_filter_single_thread(
    file_path,
    taps=DEFAULT_TAP_COUNT,
    band_gains_db=None,
    ring_buffer_size_bytes=DEFAULT_RING_BUFFER_SIZE_BYTES,
    filter_type=FILTER_TYPE_CHEBYSHEV,
    echo_enabled=False,
    clipping_enabled=False,
    reverb_enabled=None,
):
    player = EqualizerPlayer(
        file_path,
        BUFFER_MODE_SINGLE_THREAD,
        filter_type,
        taps,
        ring_buffer_size_bytes,
        band_gains_db,
        echo_enabled,
        clipping_enabled,
        reverb_enabled,
    )
    player.play()


def play_wav_with_filter_shifting_buffer(
    file_path,
    taps=DEFAULT_TAP_COUNT,
    band_gains_db=None,
    ring_buffer_size_bytes=DEFAULT_RING_BUFFER_SIZE_BYTES,
    filter_type=FILTER_TYPE_CHEBYSHEV,
    echo_enabled=False,
    clipping_enabled=False,
    reverb_enabled=None,
):
    player = EqualizerPlayer(
        file_path,
        BUFFER_MODE_SHIFTING,
        filter_type,
        taps,
        ring_buffer_size_bytes,
        band_gains_db,
        echo_enabled,
        clipping_enabled,
        reverb_enabled,
    )
    player.play()


if __name__ == "__main__":
    # play_wav_with_filter_single_thread("audio1.wav")
    play_wav_with_filter_dual_thread("audio.wav")
