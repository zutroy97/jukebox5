#include "Arduino.h"
#include "JukeboxPanel.h"

//template<class T> inline Print &operator <<(Print &obj, T arg) { obj.print(arg); return obj; }

JukeboxPanel::JukeboxPanel(byte ClockPin, byte DisplayEnablePin, byte Display4Pin, byte Display3Pin, byte KeyPadMatrixCPin, 
            byte OutputPin1, byte OutputPin2)
{
    _display3Line = 0; _display4Line = 0;
    _clockPin = ClockPin; _displayEnablePin = DisplayEnablePin;
    _display4Pin = Display4Pin; _display3Pin = Display3Pin;
    _keypadMatrixCpin = KeyPadMatrixCPin;
    _outputPin1 = OutputPin1; _outputPin2 = OutputPin2;

    pinMode(_clockPin, OUTPUT);
    pinMode(_displayEnablePin, OUTPUT);
    pinMode(_display4Pin, OUTPUT);
    pinMode(_display3Pin, OUTPUT);
    pinMode(_keypadMatrixCpin, OUTPUT);
    pinMode(_outputPin1, INPUT);
    pinMode(_outputPin2, INPUT);
}

byte JukeboxPanel::BuildFromSegmentList(char* segmentList)
{
    byte l = 0;
    byte result = 0;
    if (segmentList == NULL) return;
    l = strlen(segmentList);
    for (byte i=0; i < l; i++)
    {
        switch(segmentList[i])
        {
            case 'a': result += 1; break;
            case 'b': result += 2; break;
            case 'c': result += 4; break;
            case 'd': result += 8; break;
            case 'e': result += 16; break;
            case 'f': result += 32; break;
            case 'g': result += 64; break;
        }
    }
    _display3Line = result;
    _display4Line = result;
    return result;
}

void JukeboxPanel::Off()
{
    _display3Line = 0; _display4Line = 0;
    _state.led0State = 0; _state.led1State = 0;
    UpdateDisplay();
}
void JukeboxPanel::Write3(char* message)
{
    write (message, false);
}

void JukeboxPanel::Clear3()
{
    _display3Line = 0;
}
void JukeboxPanel::Clear()
{
    Clear3();
    Clear4();
    UpdateDisplay();
}

void JukeboxPanel::Write4(char* message)
{
    write (message, true);
}


void JukeboxPanel::Led0Set(bool value){
    _state.led0State = value;
    if (_state.led0State) { _display4Line |= 0x80000000;}
    else {_display4Line &= (~0x80000000); }
    UpdateDisplay();
}

void JukeboxPanel::Led1Set(bool value){
    _state.led1State = value;
    if (_state.led1State) { _display4Line |= 0x60000000;}
    else {_display4Line &= (~0x60000000); }
    UpdateDisplay();
}

void JukeboxPanel::Clear4()
{
    _display4Line &= 0xE0000000; // Leave LED0 and LED1 alone
}
void JukeboxPanel::SetRawValue3(uint32_t value){
    _display3Line = value;
}
void JukeboxPanel::SetRawValue4(uint32_t value){
    _display4Line = value;
}


void JukeboxPanel::write (char *arg, bool isDisplayLine4)
{
    byte b = 0;
    uint32_t display = 0;
    display = 0;

    strrev(arg);

    for (byte i=0; i < 4; i++)
    {
        if (arg[i]== '\0') break;
        b = GetCharacterMap(arg[i]);
        display = display << 7;
        display = display | b;
    }

    if (isDisplayLine4)
    {
        if (_state.led0State) { display |= 0x80000000; }
        if (_state.led1State) { display |= 0x60000000; }
        _display4Line = display;
    }else{
        _display3Line = display;
    }
    UpdateDisplay();
}

void JukeboxPanel::writeBit(byte Display3Value, byte Display4Value)
{
    digitalWrite(_display3Pin, Display3Value);
    digitalWrite(_display4Pin, Display4Value);
    digitalWrite(_clockPin, LOW);
    delayMicroseconds(400);
    digitalWrite(_clockPin, HIGH);
}

char JukeboxPanel::GetKey()
{
    static unsigned long lastTime = 0;
    static char lastKey = '_';
    static char lastSent = '_';
    char thisKey = GetCurrentKeypadLetter(getCurrentKeypadValue());

    if (thisKey != lastKey)
    {
        lastTime = millis();
        lastKey = thisKey;
    }

    if ((millis() - lastTime) > 50){
        if (thisKey != lastKey)
        {   // Times up, but last key has changed.
            lastKey = '_';
        }else if (lastSent != thisKey){
            lastSent = thisKey;
            return thisKey; 
        }
    }

    return '_';
}

uint16_t JukeboxPanel::getCurrentKeypadValue()
{
    uint16_t result = 0;
    digitalWrite(_displayEnablePin, LOW);
    for (byte i=0; i < 8; i++)
    {
        digitalWrite(_display4Pin, (i & 0x01));
        digitalWrite(_display3Pin, (i & 0x02));
        digitalWrite(_keypadMatrixCpin, (i & 0x04));
        result |= ( digitalRead(_outputPin1) << i);
        result |= ( digitalRead(_outputPin2) << (i + 8) );
    }
    digitalWrite(_displayEnablePin, HIGH);
    return result;
}

char JukeboxPanel::GetCurrentKeypadLetter(uint16_t raw){
    switch(raw)
    {
        case 0x7dff:
            return 'P';
        case 0xFDDF:
            return '1';
        case 0xfcff:
            return '2';
        case 0xfdf7:
            return '3';
        case 0xfdfc:
            return '4';
        case 0xedff:
            return '5';
        case 0xfdef:
            return '6';
        case 0xfd3f:
            return '7';
        case 0xF5FF:
            return '8';
        case 0xFDFB:
            return '9';
        case 0xDDFF:
            return '0';
        case 0xBDFF:
            return 'R';
        default:
            return '_';
    }
}
void JukeboxPanel::UpdateDisplay()
{
    uint32_t mask = 0;
    uint8_t mask0 = 0;
    byte i = 0;
    byte b0, b1;
    digitalWrite(_displayEnablePin, HIGH);
    writeBit(1, 1); // Start
    delayMicroseconds(400);
    for (i = 0; i < 32; i ++){
        mask = 1UL << i;
        b0 = LOW; b1 = LOW;

        if ((mask & _display3Line) > 0) { b0 = HIGH;}
        if ((mask & _display4Line) > 0) { b1 = HIGH;}
        writeBit(b0, b1);
    }
    // 33 bits written. Must write a total of 36 to get chips to latch.
    for (i = 0; i < 4; i++)
    {
        writeBit(LOW,LOW);
    }
    // All 36 bits written
    digitalWrite(_displayEnablePin, LOW);
}

byte JukeboxPanel::GetCharacterMap(char c)
{
    if (c == ' ') { return 0; }
    if (c >= '0' && c <= '9')
    {
        return pgm_read_byte_near( _JukeboxPanel_Characters + c - '0');
    }
    if (c >= 'a' && c <= 'z')
    {
        return pgm_read_byte_near( _JukeboxPanel_Characters + c - 'a' + 10);
    }
    if (c >= 'A' && c <= 'Z')
    {
        return pgm_read_byte_near( _JukeboxPanel_Characters + c - 'A' + 10);
    }
    switch(c)
    {
        case '-': return 8; break;
    }
    return 32; // char not mapped, return underscore
}
