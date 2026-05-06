# AI Maintenance Notes

Проект - учебный программный аудиопроигрыватель с 6-полосным эквалайзером, тремя типами буфера и двумя вариантами фильтрации.

## Актуальные требования

- звуковой эффект 1: эхо;
- звуковой эффект 2: клиппинг;
- количество полос эквалайзера: 6;
- основной тип фильтра: БИХ Чебышева II рода;
- альтернативный тип фильтра: КИХ с окном Чебышева.

## Структура

```text
play_wav.py
util.py

buffers/
  dual_thread_ring_buffer.py
  single_thread_ring_buffer.py
  shifting_buffer.py

filters/
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
WAV bytes -> mono samples -> filter bank -> echo/clipping -> selected buffer -> PyAudio
```

`play_wav.py` содержит чтение WAV, перевод stereo в mono, конвертацию PCM bytes <-> samples, выбор буфера, выбор типа фильтра, применение эффектов и запуск воспроизведения через PyAudio.

Основные константы:

```python
FILTER_TYPE_CHEBYSHEV = "chebyshev_iir"
FILTER_TYPE_CHEBYSHEV_WINDOW_FIR = "chebyshev_window_fir"
BUFFER_MODE_DUAL_THREAD = "dual_thread"
BUFFER_MODE_SINGLE_THREAD = "single_thread"
BUFFER_MODE_SHIFTING = "shifting"
BYTES_PER_SAMPLE = 2
OUTPUT_CHANNELS = 1
```

`FILTER_TYPE_CHEBYSHEV` является основным вариантом и выбран первым в UI.

## Полосы эквалайзера

```text
1: 0-100 Hz
2: 100-300 Hz
3: 300-1000 Hz
4: 1000-3000 Hz
5: 3000-8000 Hz
6: 8000-22050 Hz
```

UI передает значения в dB от `0` до `-100`. Перевод в линейный коэффициент делает:

```python
def db_to_gain(db):
    return 10 ** (db / 20)
```

## Основной фильтр: БИХ Чебышева II рода

Реализация находится в:

```text
filters/chebyshev/chebyshev_filter_bank.py
```

`ChebyshevFilterBank` строит шесть потоковых SOS-фильтров через `scipy.signal.cheby2(..., output="sos")`:

- НЧ для первой полосы;
- полосовые фильтры для средних полос;
- ВЧ для последней полосы.

Каждый фильтр хранит состояние `zi`, поэтому обработка последовательных аудиоблоков непрерывна. При изменении слайдера пересчитывается только gain соответствующей полосы.

## Альтернативный фильтр: КИХ с окном Чебышева

Реализация находится в:

```text
filters/chebyshev_window/chebyshev_window_filter_bank.py
```

`ChebyshevWindowFirFilterBank` строит суммарную АЧХ 6-полосного эквалайзера, получает импульсную характеристику через `irfft`, берет центральный фрагмент длиной `DEFAULT_TAP_COUNT` и применяет окно Чебышева `scipy.signal.windows.chebwin`.

## Эффекты

Эффекты находятся в `play_wav.py` и применяются после эквалайзера.

### Эхо

Класс:

```python
EchoEffect
```

Это delay-line эффект с обратной связью:

```python
DEFAULT_ECHO_DELAY_MS = 220
DEFAULT_ECHO_FEEDBACK = 0.35
DEFAULT_ECHO_WET = 0.4
```

Для обратной совместимости `ReverbEffect` оставлен как alias к `EchoEffect`, а `set_reverb_enabled(...)` вызывает `set_echo_enabled(...)`.

### Клиппинг

Функция:

```python
clip_samples(...)
```

Это hard clipping по порогу:

```python
DEFAULT_CLIPPING_THRESHOLD = 12000
```

Финальная защита диапазона int16 остается в `clamp_int16(...)`.

## UI

Главный файл:

```text
ui/main_window.py
```

Интерфейс позволяет выбрать WAV-файл, тип буфера, тип фильтра, включить эхо/клиппинг, изменить размер буфера и отрегулировать 6 полос эквалайзера.

Типы фильтров в UI:

```text
БИХ Чебышева II рода
КИХ, окно Чебышева
```

Эффекты в UI:

```text
[ ] Эхо
[ ] Клиппинг
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
