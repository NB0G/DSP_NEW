# AI Maintenance Notes

Проект - учебный программный аудиопроигрыватель с 8-полосным эквалайзером, тремя типами буфера и двумя вариантами фильтрации.

## Актуальные требования

- звуковой эффект 1: реверберация;
- звуковой эффект 2: вибрато;
- количество полос эквалайзера: 8;
- основной тип фильтра: КИХ с окном Чебышева;
- альтернативный тип фильтра: БИХ Чебышева II рода.

## Структура

```text
play_wav.py
util.py

buffers/
  dual_thread_ring_buffer.py
  single_thread_ring_buffer.py
  shifting_buffer.py

filters/
  equalizer_bands.py
  chebyshev/
    chebyshev_filter_bank.py
  chebyshev_window/
    chebyshev_window_filter_bank.py
  sinc/
    legacy sinc FIR modules

ui/
  main_window.py
```

## Обработка звука

Главная цепочка:

```text
WAV bytes -> mono samples -> filter bank -> reverb/vibrato -> selected buffer -> PyAudio
```

`play_wav.py` содержит чтение WAV, перевод stereo в mono, конвертацию PCM bytes <-> samples, выбор буфера, выбор типа фильтра, применение эффектов и запуск воспроизведения через PyAudio.

Основные константы:

```python
FILTER_TYPE_CHEBYSHEV = "chebyshev_iir"
FILTER_TYPE_CHEBYSHEV_WINDOW_FIR = "chebyshev_window_fir"
DEFAULT_FILTER_TYPE = FILTER_TYPE_CHEBYSHEV_WINDOW_FIR
BUFFER_MODE_DUAL_THREAD = "dual_thread"
BUFFER_MODE_SINGLE_THREAD = "single_thread"
BUFFER_MODE_SHIFTING = "shifting"
BYTES_PER_SAMPLE = 2
OUTPUT_CHANNELS = 1
```

`FILTER_TYPE_CHEBYSHEV_WINDOW_FIR` является основным вариантом и выбран первым в UI. `FILTER_TYPE_CHEBYSHEV` оставлен как альтернативный БИХ-вариант.

## Полосы эквалайзера

```text
1: 0-100 Hz
2: 100-300 Hz
3: 300-700 Hz
4: 700-1500 Hz
5: 1500-3100 Hz
6: 3100-6300 Hz
7: 6300-12700 Hz
8: 12700-22050 Hz
```

Единый список полос хранится в `filters/equalizer_bands.py`; UI и оба filter bank используют этот список.

UI передает значения в dB от `0` до `-100`. Перевод в линейный коэффициент делает:

```python
def db_to_gain(db):
    return 10 ** (db / 20)
```

## Основной фильтр: КИХ с окном Чебышева

Реализация находится в:

```text
filters/chebyshev_window/chebyshev_window_filter_bank.py
```

`ChebyshevWindowFirFilterBank` строит суммарную АЧХ 8-полосного эквалайзера, получает импульсную характеристику через `irfft`, берет центральный фрагмент длиной `DEFAULT_TAP_COUNT` и применяет окно Чебышева `scipy.signal.windows.chebwin`.

## Альтернативный фильтр: БИХ Чебышева II рода

Реализация находится в:

```text
filters/chebyshev/chebyshev_filter_bank.py
```

`ChebyshevFilterBank` строит 8 потоковых SOS-фильтров через `scipy.signal.cheby2(..., output="sos")`:

- НЧ для первой полосы;
- полосовые фильтры для средних полос;
- ВЧ для последней полосы.

Каждый фильтр хранит состояние `zi`, поэтому обработка последовательных аудиоблоков непрерывна. При изменении слайдера пересчитывается только gain соответствующей полосы.

## Эффекты

Эффекты находятся в `play_wav.py` и применяются после эквалайзера.

### Реверберация

Класс:

```python
ReverbEffect
```

Это несколько delay-line линий с обратной связью и damping:

```python
DEFAULT_REVERB_DELAYS_MS = (23, 31, 47, 61, 83, 107)
DEFAULT_REVERB_FEEDBACK = 0.72
DEFAULT_REVERB_WET = 0.75
DEFAULT_REVERB_DAMPING = 0.22
```

### Вибрато

Класс:

```python
VibratoEffect
```

Это потоковый модулируемый delay-line с линейной интерполяцией:

```python
DEFAULT_VIBRATO_RATE_HZ = 5.0
DEFAULT_VIBRATO_DEPTH_MS = 6.0
DEFAULT_VIBRATO_BASE_DELAY_MS = 8.0
```

Финальная защита диапазона int16 остается в `clamp_int16(...)`.

## UI

Главный файл:

```text
ui/main_window.py
```

Интерфейс позволяет выбрать WAV-файл, тип буфера, тип фильтра, включить реверберацию/вибрато, изменить размер буфера и отрегулировать 8 полос эквалайзера.

Типы фильтров в UI:

```text
КИХ, окно Чебышева
БИХ Чебышева II рода
```

Эффекты в UI:

```text
[ ] Реверберация
[ ] Вибрато
```

## Проверка после изменений

Минимальная проверка синтаксиса:

```powershell
python -m compileall .
```

Запуск UI:

```powershell
python ui\main_window.py
```
