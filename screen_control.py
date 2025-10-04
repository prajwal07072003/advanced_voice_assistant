import screen_brightness_control as sbc
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
import subprocess
import re


# --------------------------
# BRIGHTNESS CONTROL
# --------------------------
def set_brightness(level):
    """Set screen brightness (0-100%)"""
    try:
        sbc.set_brightness(level)
        return f"Set brightness to {level}%"
    except Exception as e:
        return f"Brightness error: {str(e)}"


def get_brightness():
    """Get current brightness level"""
    return f"Current brightness is {sbc.get_brightness()[0]}%"


# --------------------------
# VOLUME CONTROL
# --------------------------
def setup_audio():
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(
        IAudioEndpointVolume._iid_,
        CLSCTX_ALL,
        None
    )
    return cast(interface, POINTER(IAudioEndpointVolume))


volume_control = setup_audio()


def set_volume(level):
    """Set system volume (0-100)"""
    try:
        volume_control.SetMasterVolumeLevelScalar(level / 100, None)
        return f"Volume set to {level}%"
    except Exception as e:
        return f"Volume error: {str(e)}"


def get_volume():
    """Get current volume level"""
    current = round(volume_control.GetMasterVolumeLevelScalar() * 100)
    return f"Volume is at {current}%"


# --------------------------
# DISPLAY MANAGEMENT
# --------------------------
def turn_off_display():
    """Turn off the main display"""
    try:
        subprocess.run(['xset', 'dpms', 'force', 'off'])  # Linux
        # Windows alternative: nircmd.exe monitor off
        return "Display turned off"
    except:
        return "Display control not supported"


def set_resolution(width, height):
    """Change screen resolution"""
    try:
        subprocess.run(['xrandr', '--output', 'eDP-1', '--mode', f'{width}x{height}'])  # Linux
        return f"Resolution set to {width}x{height}"
    except:
        return "Resolution change failed"


# --------------------------
# VOICE COMMAND PARSING
# --------------------------
def handle_screen_command(command):
    """Process screen-related voice commands"""
    command = command.lower()

    # Brightness control
    if 'brightness' in command:
        if 'current' in command or 'what is' in command:
            return get_brightness()
        elif 'max' in command:
            return set_brightness(100)
        elif 'min' in command:
            return set_brightness(0)
        else:
            match = re.search(r'(\d{1,3})%', command)
            if match:
                return set_brightness(int(match.group(1)))
            elif 'increase' in command:
                current = sbc.get_brightness()[0]
                return set_brightness(min(100, current + 20))
            elif 'decrease' in command:
                current = sbc.get_brightness()[0]
                return set_brightness(max(0, current - 20))

    # Volume control
    elif 'volume' in command:
        if 'current' in command or 'what is' in command:
            return get_volume()
        elif 'mute' in command:
            volume_control.SetMute(1, None)
            return "Volume muted"
        elif 'unmute' in command:
            volume_control.SetMute(0, None)
            return "Volume unmuted"
        else:
            match = re.search(r'(\d{1,3})%', command)
            if match:
                return set_volume(int(match.group(1)))

    # Display control
    elif 'turn off display' in command:
        return turn_off_display()

    return "Screen command not recognized"