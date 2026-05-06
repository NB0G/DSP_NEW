import os
import sys

from PyQt5.QtCore import QObject, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtCore import Qt

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from play_wav import (
    BUFFER_MODE_DUAL_THREAD,
    BUFFER_MODE_SHIFTING,
    BUFFER_MODE_SINGLE_THREAD,
    BYTES_PER_SAMPLE,
    DEFAULT_RING_BUFFER_SIZE_BYTES,
    DUAL_THREAD_INPUT_FRAMES_PER_CYCLE,
    EqualizerPlayer,
    FILTER_TYPE_CHEBYSHEV,
    FILTER_TYPE_CHEBYSHEV_WINDOW_FIR,
    SINGLE_THREAD_INPUT_FRAMES_PER_CYCLE,
)
from filters.equalizer_bands import EQUALIZER_BANDS


BANDS = [
    (band_number, f"{low_cutoff_hz}-{high_cutoff_hz} Hz")
    for band_number, (low_cutoff_hz, high_cutoff_hz) in enumerate(
        EQUALIZER_BANDS,
        start=1,
    )
]


class PlayerWorker(QObject):
    finished = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(
        self,
        file_path,
        buffer_mode,
        filter_type,
        ring_buffer_size_bytes,
        band_gains_db,
        reverb_enabled,
        vibrato_enabled,
    ):
        super().__init__()
        self.player = EqualizerPlayer(
            file_path=file_path,
            buffer_mode=buffer_mode,
            filter_type=filter_type,
            ring_buffer_size_bytes=ring_buffer_size_bytes,
            band_gains_db=band_gains_db,
            reverb_enabled=reverb_enabled,
            vibrato_enabled=vibrato_enabled,
        )

    def run(self):
        try:
            self.player.play()
        except Exception as error:
            self.failed.emit(str(error))
        finally:
            self.finished.emit()

    def stop(self):
        self.player.stop()

    def set_band_gain(self, band_number, gain_db):
        self.player.set_band_gain(band_number, gain_db)

    def set_reverb_enabled(self, enabled):
        self.player.set_reverb_enabled(enabled)

    def set_vibrato_enabled(self, enabled):
        self.player.set_vibrato_enabled(enabled)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DSP Equalizer")
        self.file_path = ""
        self.worker = None
        self.thread = None
        self.reset_requested = False
        self.gain_labels = {}
        self.gain_sliders = {}

        self.build_ui()

    def build_ui(self):
        central = QWidget()
        layout = QVBoxLayout(central)

        layout.addWidget(self.build_file_group())
        layout.addWidget(self.build_buffer_group())
        layout.addWidget(self.build_effect_group())
        layout.addWidget(self.build_band_group())
        layout.addLayout(self.build_buttons())

        self.setCentralWidget(central)
        self.resize(920, 520)

    def build_file_group(self):
        group = QGroupBox("Файл")
        layout = QHBoxLayout(group)

        self.file_label = QLabel("Файл не выбран")
        browse_button = QPushButton("Выбрать WAV")
        browse_button.clicked.connect(self.choose_file)

        layout.addWidget(self.file_label, 1)
        layout.addWidget(browse_button)
        return group

    def build_effect_group(self):
        group = QGroupBox("Эффекты")
        layout = QHBoxLayout(group)

        self.reverb_enabled = QCheckBox("Реверберация")
        self.vibrato_enabled = QCheckBox("Вибрато")

        self.reverb_enabled.toggled.connect(self.change_reverb_enabled)
        self.vibrato_enabled.toggled.connect(self.change_vibrato_enabled)

        layout.addWidget(self.reverb_enabled)
        layout.addWidget(self.vibrato_enabled)
        layout.addStretch(1)

        return group

    def build_buffer_group(self):
        group = QGroupBox("Буфер")
        layout = QGridLayout(group)

        self.buffer_mode = QComboBox()
        self.buffer_mode.addItem("Двухпоточный", BUFFER_MODE_DUAL_THREAD)
        self.buffer_mode.addItem("Однопоточный", BUFFER_MODE_SINGLE_THREAD)
        self.buffer_mode.addItem("Смещающий", BUFFER_MODE_SHIFTING)

        self.filter_type = QComboBox()
        self.filter_type.addItem(
            "КИХ, окно Чебышева",
            FILTER_TYPE_CHEBYSHEV_WINDOW_FIR,
        )
        self.filter_type.addItem("БИХ Чебышева II рода", FILTER_TYPE_CHEBYSHEV)

        self.ring_buffer_size_bytes = QSpinBox()
        self.ring_buffer_size_bytes.setRange(2, 512)
        self.ring_buffer_size_bytes.setSingleStep(2)
        self.ring_buffer_size_bytes.setValue(DEFAULT_RING_BUFFER_SIZE_BYTES)

        layout.addWidget(QLabel("Тип буфера"), 0, 0)
        layout.addWidget(self.buffer_mode, 0, 1)
        layout.addWidget(QLabel("Тип фильтра"), 0, 2)
        layout.addWidget(self.filter_type, 0, 3)
        layout.addWidget(QLabel("Размер буфера, байт"), 1, 0)
        layout.addWidget(self.ring_buffer_size_bytes, 1, 1)

        return group

    def build_band_group(self):
        group = QGroupBox("Полосы, дБ")
        layout = QHBoxLayout(group)

        for band_number, label_text in BANDS:
            band_layout = QVBoxLayout()
            title = QLabel(label_text)
            title.setAlignment(Qt.AlignCenter)

            value_label = QLabel("0 dB")
            value_label.setAlignment(Qt.AlignCenter)

            slider = QSlider(Qt.Vertical)
            slider.setRange(-100, 0)
            slider.setValue(0)
            slider.valueChanged.connect(
                lambda value, band=band_number: self.change_band_gain(band, value)
            )

            self.gain_labels[band_number] = value_label
            self.gain_sliders[band_number] = slider

            band_layout.addWidget(title)
            band_layout.addWidget(slider, 1)
            band_layout.addWidget(value_label)
            layout.addLayout(band_layout)

        return group

    def build_buttons(self):
        layout = QHBoxLayout()

        self.play_button = QPushButton("Старт")
        self.stop_button = QPushButton("Стоп")
        self.stop_button.setEnabled(False)
        self.status_label = QLabel("Готово")

        self.play_button.clicked.connect(self.start_playback)
        self.stop_button.clicked.connect(self.reset_playback)

        layout.addStretch(1)
        layout.addWidget(self.status_label)
        layout.addWidget(self.play_button)
        layout.addWidget(self.stop_button)

        return layout

    def choose_file(self):
        file_path, _filter = QFileDialog.getOpenFileName(
            self,
            "Выбрать WAV",
            os.getcwd(),
            "WAV files (*.wav)",
        )

        if file_path:
            self.file_path = file_path
            self.file_label.setText(file_path)

    def current_band_gains(self):
        return {
            band_number: slider.value()
            for band_number, slider in self.gain_sliders.items()
        }

    def current_reverb_enabled(self):
        return self.reverb_enabled.isChecked()

    def current_vibrato_enabled(self):
        return self.vibrato_enabled.isChecked()

    def current_ring_buffer_size_bytes(self):
        value = self.ring_buffer_size_bytes.value()
        buffer_mode = self.buffer_mode.currentData()

        if buffer_mode == BUFFER_MODE_SHIFTING:
            remainder = value % 4
            if remainder != 0:
                value = min(
                    value + (4 - remainder),
                    self.ring_buffer_size_bytes.maximum(),
                )
                self.ring_buffer_size_bytes.setValue(value)
        elif buffer_mode == BUFFER_MODE_DUAL_THREAD:
            min_ring_buffer_size = (
                DUAL_THREAD_INPUT_FRAMES_PER_CYCLE * BYTES_PER_SAMPLE
            )
            if value < min_ring_buffer_size:
                value = min_ring_buffer_size

            if value % 2 != 0:
                value = min(value + 1, self.ring_buffer_size_bytes.maximum())

            self.ring_buffer_size_bytes.setValue(value)
        else:
            min_ring_buffer_size = (
                SINGLE_THREAD_INPUT_FRAMES_PER_CYCLE * BYTES_PER_SAMPLE
            )
            if value < min_ring_buffer_size:
                value = min_ring_buffer_size

            if value % 2 != 0:
                value = min(value + 1, self.ring_buffer_size_bytes.maximum())

            self.ring_buffer_size_bytes.setValue(value)

        return value

    def change_band_gain(self, band_number, gain_db):
        self.gain_labels[band_number].setText(f"{gain_db} dB")

        if self.worker is not None:
            self.worker.set_band_gain(band_number, gain_db)

    def change_reverb_enabled(self, enabled):
        if self.worker is not None:
            self.worker.set_reverb_enabled(enabled)

    def change_vibrato_enabled(self, enabled):
        if self.worker is not None:
            self.worker.set_vibrato_enabled(enabled)

    def start_playback(self):
        if not self.file_path:
            return

        if self.worker is not None:
            return

        self.reset_requested = False
        self.thread = QThread()
        self.worker = PlayerWorker(
            file_path=self.file_path,
            buffer_mode=self.buffer_mode.currentData(),
            filter_type=self.filter_type.currentData(),
            ring_buffer_size_bytes=self.current_ring_buffer_size_bytes(),
            band_gains_db=self.current_band_gains(),
            reverb_enabled=self.current_reverb_enabled(),
            vibrato_enabled=self.current_vibrato_enabled(),
        )
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.playback_failed)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.playback_finished)

        self.play_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_label.setText("Воспроизведение")
        self.thread.start()

    def reset_playback(self):
        self.reset_requested = True
        self.stop_button.setEnabled(False)
        self.status_label.setText("Сброс")

        if self.worker is not None:
            self.worker.stop()
        else:
            self.playback_finished()

    def playback_finished(self):
        self.worker = None
        finished_thread = self.thread
        self.thread = None

        if finished_thread is not None:
            finished_thread.deleteLater()

        self.play_button.setEnabled(True)
        self.stop_button.setEnabled(False)

        if self.reset_requested:
            self.status_label.setText("Сброшено")
        else:
            self.status_label.setText("Готово")

    def playback_failed(self, message):
        self.status_label.setText(f"Ошибка: {message}")


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
