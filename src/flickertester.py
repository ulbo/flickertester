# Display flicker curve on I2C driven SH1106 OLED display
#
# Platform: MicroPython on Raspberry Pico
# Photodiode: OPT101 (for circuit see https://www.electroschematics.com/photodiode/)
# Display: SH1106 OLED display
#
# OPT101/ADC characteristics: Min: 0V / 300 digits
#                             Max: 2.5V / 3100 digits
#
# Libraries: SH1106 driver from https://github.com/robert-hh/SH1106

from machine import I2C, ADC, Pin
from sh1106 import SH1106_I2C
import framebuf
import time, array, uctypes, rp_devices as devs

SCREEN_WIDTH  = 128         # OLED display width
SCREEN_HEIGHT = 64          # OLED display height

NSAMPLES = 1200             # number of samples taken from ADC
SAMPLING_RATE = 20000       # ADC sampling rate

# =====================================================================
# Helper functions for display graphics
# ---------------------------------------------------------------------
def pset(x: int, y: int, col:int):
    """Set pixel with upright coordinate system"""
    # pyxel.pset(x, SCREEN_HEIGHT - y, col)
    oled.pixel(x, y, 1)

# ---------------------------------------------------------------------
def line(x1: int, y1: int, x2: int, y2: int, col:int):
    """Draw line with upright coordinate system"""
    # pyxel.line(x1, SCREEN_HEIGHT - y1, x2, SCREEN_HEIGHT - y2, col)
    oled.line(x1, y1, x2, y2, 1)

# ---------------------------------------------------------------------
def vline_dot(x: int):
    "Draw a vertical dotted line"
    for y in range(0, SCREEN_HEIGHT, 4):
        oled.pixel(x, y, 1)

# ---------------------------------------------------------------------
def text(x: int, y: int, s: str, col:int):
    # pyxel.text( x, SCREEN_HEIGHT - y, s, col)
    oled.text(s, int(x), int(y))


# =====================================================================
# OLED functions
# ---------------------------------------------------------------------
# Init I2C using given Pins
def init_i2c():
    i2c = I2C(0, sda=Pin(20), scl=Pin(21), freq=400000)

    print("I2C Address      : "+hex(i2c.scan()[0]).upper()) # Display device address
    print("I2C Configuration: "+str(i2c))                   # Display I2C config
    return i2c

# ---------------------------------------------------------------------
def init_oled(i2c):
    oled = SH1106_I2C(SCREEN_WIDTH, SCREEN_HEIGHT, i2c)     # Init oled display

    # Clear the oled display in case it has junk on it.
    oled.fill(0)

    # Display is built-in upside down
    oled.flip()
    return oled

# ---------------------------------------------------------------------
def oled_demo():
    """Just to test OLED functions"""
    # Add some text
    oled.text("Raspberry Pi",5,5)
    oled.text("Pico",5,15)

    # draw something
    for i in range(5, 120, 2):
        oled.pixel(i, 50, 1)

    w = SCREEN_WIDTH-1
    h = SCREEN_HEIGHT-1

    oled.line(0, 0, w, h, 1)
    oled.line(0, h, w, 0, 1)
    x = int(w / 2)
    y = int(h / 2)
    oled.ellipse(x, y, x, y, 1)

    # Finally update the oled display so the image & text is displayed
    oled.show()

# =====================================================================
# ADC functions
# ---------------------------------------------------------------------
def init_adc(channel = 0):
    """Initialize ADC"""

    # Fetch single ADC sample
    ADC_CHAN = channel
    ADC_PIN  = 26 + ADC_CHAN

    adc = devs.ADC_DEVICE
    pin = devs.GPIO_PINS[ADC_PIN]
    pad = devs.PAD_PINS[ADC_PIN]
    pin.GPIO_CTRL_REG = devs.GPIO_FUNC_NULL
    pad.PAD_REG = 0
    time.sleep_ms(1)
    return adc


# ---------------------------------------------------------------------
def adc_get_value(adc, channel = 0):
    """Get a single measurement from ADC"""

    adc.CS_REG = adc.FCS_REG = 0
    adc.CS.EN = 1
    adc.CS.AINSEL = channel
    adc.CS.START_ONCE = 1
    val = adc.RESULT_REG

    return val


# ---------------------------------------------------------------------
def adc_get_wave(adc, nsamples, sampling_rate, channel=0):
    """Get multiple samples from ADC using DMA"""
    # idea and code borrowed from https://iosoft.blog/2021/10/26/pico-adc-dma/

    adc.CS_REG = adc.FCS_REG = 0
    adc.CS.EN = 1
    adc.CS.AINSEL = channel
    adc.CS.START_ONCE = 1

    # Multiple ADC samples using DMA
    DMA_CHAN = 0
    dma_chan = devs.DMA_CHANS[DMA_CHAN]
    dma = devs.DMA_DEVICE

    adc.FCS.EN = adc.FCS.DREQ_EN = 1
    adc_buff = array.array('H', (0 for _ in range(NSAMPLES)))
    adc.DIV_REG = (48000000 // sampling_rate - 1) << 8
    adc.FCS.THRESH = adc.FCS.OVER = adc.FCS.UNDER = 1

    dma_chan.READ_ADDR_REG = devs.ADC_FIFO_ADDR
    dma_chan.WRITE_ADDR_REG = uctypes.addressof(adc_buff)
    dma_chan.TRANS_COUNT_REG = nsamples

    dma_chan.CTRL_TRIG_REG = 0
    dma_chan.CTRL_TRIG.CHAIN_TO = DMA_CHAN
    dma_chan.CTRL_TRIG.INCR_WRITE = dma_chan.CTRL_TRIG.IRQ_QUIET = 1
    dma_chan.CTRL_TRIG.TREQ_SEL = devs.DREQ_ADC
    dma_chan.CTRL_TRIG.DATA_SIZE = 1
    dma_chan.CTRL_TRIG.EN = 1

    while adc.FCS.LEVEL:
        x = adc.FIFO_REG

    adc.CS.START_MANY = 1

    # wait for DMA to finish
    while dma_chan.CTRL_TRIG.BUSY:
        time.sleep_ms(10)
    adc.CS.START_MANY = 0
    dma_chan.CTRL_TRIG.EN = 0

    # print(adc_buff)
    return adc_buff

# ---------------------------------------------------------------------
def scale(x1: float, x2: float, y1: float, y2: float) -> tuple[float]:
    """Calculate gain (slope) and offset (intersection with x-axis)
       of linear equation from two points (x1, y1), (x2, y2).
       from
    """
    gain = (y2 - y1) / (x2 - x1)
    offset = (y1*x2 - y2*x1) / (x2 - x1)

    return (gain, offset)

# ---------------------------------------------------------------------
def find_period(wv: list[int]) -> tuple:
    """
    Find first, mid and last index belonging to one period of wave {wv}.
    :param wv: wave as list of integers

    :return:    tuple of indices in {wv}: (first, middle, last) sample
                of one period
    """

    wv_max = max(wv)
    wv_min = min(wv)

    average = (wv_max + wv_min) / 2.
    trigger_level = (wv_max - average) * 0.3
    first = mid = last = 0
    threshold = average - trigger_level
    # print(wv_min, wv_max, trigger_level)

    # initialize: search for falling edge first
    for i, y in enumerate(wv):

        if y < threshold:
            first = i
            threshold = average + trigger_level
            break

    # search for i where (y - {average}) changes polarity
    for i in range(first, len(wv)):
        y = wv[i]

        if y > threshold:
            first = i
            threshold = average - trigger_level
            break

    # search for falling edge
    for i in range(first, len(wv)):
        y = wv[i]

        if y < threshold:
            mid = i
            threshold = average + trigger_level
            break

    # search for rising edge again
    for i in range(mid, len(wv)):
        y = wv[i]

        if y > threshold:
            last = i
            break

    return (first, mid, last)

# ---------------------------------------------------------------------
def filter_wave(wave: list[int]) -> list[int]:
    """Filter algorithm designed using http://t-filter.engineerjs.com
    Sampling rate: 20000 Hz
    Specs:
        * 0 Hz - 2000 Hz
        gain = 1
        desired ripple = 5 dB
        actual ripple = 4.024246464355393 dB

        * 6000 Hz - 10000 Hz
        gain = 0
        desired attenuation = -60 dB
        actual attenuation = -60.309797420786424 dB
    """

    FILTER_TAPS = [
            0.007368171996559226,
            0.04974402650118188,
            0.1447129657129954,
            0.2573965885895257,
            0.30915399294515716,
            0.2573965885895257,
            0.1447129657129954,
            0.04974402650118188,
            0.007368171996559226
    ]

    wave_out = []

    for i in range(len(wave)):
        # print(f"{wave[i]}:", end="   ")
        val = 0.
        for t in range(len(FILTER_TAPS)):
            if i + t < len(wave):
                val += wave[i + t] * FILTER_TAPS[t]
                # print(f"{val}", end=" ")

        wave_out.append(int(val))
        # print(f"   [{val}]")

    return wave_out

# ---------------------------------------------------------------------
def display_wave(wave: list[int],
                 sampling_rate: int,
                 screen_width: int,
                 screen_height: int):

    if True:
        # denoise wave
        wv = filter_wave(wave)
        
        # The 9th order FIR filter distorts the last 9 samples of the waveform,
        # so we cut these here.
        wv = wv[0:len(wv)-10]
    else:
        wv = []

        for i, v in enumerate(wave):
            if i < 1:
                wv.append(int(v))
            else:
                wv.append(int((v + prev) / 2.))

            prev = v


    # calculate period of wave
    n1, n2, n3 = find_period(wv)

    # emergency exit if flicker frequency too high
    if n3 - n1 < 3:
        # for n in wv:
        #     print(n)
        print(f"Frequency too high: n1={n1} n3={n3}")
        return

    # calculate part of wave that will be displayed on screen
    # we will show one full period of wave plus about 10% at each side

    # calculate factors to scale wave to fit in screen
    screen_range_x = n3 - n1
    padding = 0.1
    screen_x1 = int(n1 - screen_range_x * padding)
    screen_x2 = int(n3 + screen_range_x * padding)
    screen_scaling = (screen_x2 - screen_x1) / screen_width

    ymin = min(wv)
    ymax = max(wv)
    screen_low = screen_height * 0.05   # lowest value in screen coordinates for wave
    screen_high = screen_height * 0.95  # highest value

    gain, offset = scale(ymin, ymax, screen_low, screen_high)

    # wv_screen = []
    # for i in range(screen_width):
    #     wv_screen.append(wv[int(i * screen_scaling + screen_x1)] * gain + offset)
    wv_screen = [int(wv[int(i * screen_scaling + screen_x1)] * gain + offset) for i in range(screen_width)]

    # calculate index of first and last x value of period
    marker1 = int((n1 - screen_x1) / screen_scaling)
    marker2 = screen_width - int((screen_x2 - n3) / screen_scaling)

    frequency = sampling_rate / (n3 - n1)

    # scale average to match wave and show it
    average = (min(wv) + max(wv)) / 2.
    average = int(average * gain + offset)
    line(0, average, screen_width, average, 1)

    # show first and last x value of period
    vline_dot(marker1)
    vline_dot(marker2)

    # draw wave
    for x in range(screen_width):
        y = wv_screen[x]
        
        if x == 0:
            pset(x, y, 10)
        else:
            line(x_prev, y_prev, x, y, 10)
            
        x_prev = x
        y_prev = y

    # text(0, SCREEN_HEIGHT - 10, f"{round(100*(ymax - ymin) / ymax)}%", 1)
    text(0, 0, f"{ymax}", 1)
    text(0, SCREEN_HEIGHT - 10, f"{ymin}", 1)
    text(SCREEN_WIDTH / 2, SCREEN_HEIGHT - 10, f"{round(frequency, 1):5.1f}Hz", 1)

# ---------------------------------------------------------------------
def main():

    global oled
    oled = init_oled(init_i2c())
    adc = init_adc()

    while(1):

        # measure light intensity
        wv = adc_get_wave(adc, NSAMPLES, SAMPLING_RATE)

        maximum = max(wv)
        minimum = min(wv)
        avg = int((maximum + minimum) / 2.)

        oled.fill(0)

        # if we have no flicker, then display average light intensity
        # otherwise display wave
        if maximum - minimum < 200:
            oled.text(f"{avg}", 5, 24)
        else:
            display_wave(wv, SAMPLING_RATE, SCREEN_WIDTH, SCREEN_HEIGHT)

        # update the oled display so image & text are displayed
        oled.show()


if __name__ == '__main__':
    main()
