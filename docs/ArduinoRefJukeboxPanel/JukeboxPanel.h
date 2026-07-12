#ifndef JukeboxPanel_h
#define JukeboxPanel_h

#include "Arduino.h"

// Lookup required for generating LED patterns. Defined here so it will work with PROGMEM.
// From https://www.arduino.cc/reference/en/language/variables/utilities/progmem/ (Notes and Warnings)
// Please note that variables must be either globally defined, OR defined with the static keyword, in order to work with PROGMEM.
const static byte _JukeboxPanel_Characters[36] PROGMEM = {
    119,    // 0
    65,
    59,
    107,
    77,
    110,    // 5
    126,
    67,
    127,
    111,    // 9
    95,     // A
    124,    // B
    54,     // C
    121,    // D
    62,     // E
    30,     // f
    111,    // g
    92,     // h
    20,     // i
    113,    // j
    93,     // k
    52,     // l
    82,     // m
    88,     // n
    120,    // o
    31,     // p
    79,     // q
    24 ,    // r
    110,    // s
    60,     // t
    117,    // u
    112,    // v
    37,     // w
    93,     // x
    109,    // y
    59      // z
};
typedef struct {
    byte led0State : 1;
    byte led1State : 1;
    byte unused : 6;
} JukeboxPanelState_t;

class JukeboxPanel
{
    public:
        JukeboxPanel(byte ClockPin, byte DisplayEnablePin, byte Display4Pin, byte Display3Pin, byte KeyPadMatrixCPin, 
            byte OutputPin1, byte OutputPin2);
        byte GetCharacterMap(char c); // Value needed to display char c
        void UpdateDisplay(); // Write out _displayLine3 and _displayLine4 values to the display
        void Write3(char* message); // Write out the string to the 3 digit display
        void Clear3(); // Clear the 3 digit display
        void Write4(char* message); // Write out the string to the 4 digit display
        void Clear4();  // Clear the 4 digit display
        void SetRawValue3(uint32_t value);  // Write this value to the _displayLine3
        void SetRawValue4(uint32_t value);  // Write this value to the _displayLine4
        byte BuildFromSegmentList(char* segmentList); // Lights and displays the value for the segments (abcdef) passed in.
        void Led0Set(bool value);
        void Led1Set(bool value);
        uint16_t getCurrentKeypadValue();
        char GetCurrentKeypadLetter(uint16_t raw);
        char GetKey();
        void Off(); // Turn off all Led0s
        void Clear(); // Blank all 7 segment leds, led0 and led1 unaffected
    private:
        byte _clockPin;
        byte _displayEnablePin;
        byte _display4Pin;
        byte _display3Pin;
        byte _keypadMatrixCpin;
        byte _outputPin1;
        byte _outputPin2;
        uint32_t _display3Line;
        uint32_t _display4Line;
        void write (char *arg, bool isDisplay4);
        void writeBit(byte Display3Value, byte Display4Value);
        JukeboxPanelState_t _state;

};

#endif