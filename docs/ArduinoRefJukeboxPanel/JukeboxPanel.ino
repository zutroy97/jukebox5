#include <SerialCommand.h>
#include "JukeboxPanel.h"
#define DISPLAY_CLOCK   2
#define DISPLAY_ENABLE  4
#define DISPLAY_Z8_DATA 7
#define DISPLAY_Z3_DATA 8
#define KEYPAD_MATRIX_C 12
#define KEYPAD_IN_0 13
#define KEYPAD_IN_1 14

JukeboxPanel jbPanel ( DISPLAY_CLOCK , DISPLAY_ENABLE , DISPLAY_Z8_DATA , DISPLAY_Z3_DATA , KEYPAD_MATRIX_C , KEYPAD_IN_0 , KEYPAD_IN_1 );

template<class T> inline Print &operator <<(Print &obj, T arg) { obj.print(arg); return obj; }

typedef struct Status_t
{
    uint16_t timer_10ms;
    unsigned long lastTick;
};
Status_t status;

SerialCommand sCmd;
char *temp_c;
char *blank = "    ";

void printPrompt()
{
  Serial << (F("READY>\n"));
}

void functRaw()
{∏
    unsigned long x = 0;
    temp_c = sCmd.next();
    if (temp_c != NULL){
        x = atol(temp_c);
        jbPanel.SetRawValue3(x);
        jbPanel.SetRawValue4(x);
        jbPanel.UpdateDisplay();
    }    
    printPrompt();
}

void functWrite3()
{
    temp_c = sCmd.next();
    if (temp_c == NULL) {jbPanel.Clear3(); jbPanel.UpdateDisplay(); return;}
    jbPanel.Write3(temp_c);
    printPrompt();
}
void functWrite4()
{
    temp_c = sCmd.next();
    if (temp_c == NULL) {
        temp_c = blank;
    }
    jbPanel.Write4(temp_c);
    printPrompt();
}
void functClear()
{
    jbPanel.Clear();
    printPrompt();
}

void functSegmentTest()
{
    byte result = 0;
    temp_c = sCmd.next();
    if (temp_c == NULL) return 0;
    result = jbPanel.BuildFromSegmentList(temp_c);
    //Serial << "Result: " << result << "\n";
    jbPanel.UpdateDisplay();
    printPrompt();
}

void functOff()
{
    jbPanel.Off();
    printPrompt();
}
void functLed0()
{
    temp_c = sCmd.next();
    jbPanel.Led0Set(temp_c != NULL);
    //Serial << "led0 " << (temp_c != NULL) << "\n";
    printPrompt();
}

void functLed1()
{
    temp_c = sCmd.next();
    jbPanel.Led1Set(temp_c != NULL);
    //Serial << "led1 " << (temp_c != NULL) << "\n";
    printPrompt();
}

void setup()
{
    delay(10);
    Serial.begin(9600);

    digitalWrite(DISPLAY_CLOCK, HIGH); // Active Low
    sCmd.addCommand("r", &functRaw);    // Write a raw uint32_t directly to buffer.
    sCmd.addCommand("w4", &functWrite4);    // Write message to 4 digit display
    sCmd.addCommand("w3", &functWrite3);    // Write message to 3 digit display
    sCmd.addCommand("c", &functClear);  // blank all characters...led0 and led1 unaffected.
    sCmd.addCommand("s", &functSegmentTest); // Type in segment letters, displays pattern and HEX code.
    sCmd.addCommand("led0", &functLed0);
    sCmd.addCommand("led1", &functLed1);
    sCmd.addCommand("off", &functOff); // Turn off ALL leds

    status.lastTick = millis();
    printPrompt();
}

void readKeypad2()
{
    char c = jbPanel.GetKey();
    if (c != '_')   // _ means nothing pressed
    {
        Serial << "BTN:" << c << "\n";
    }
}

void loop()
{
    unsigned long now;
    now = millis();
    if ((now - status.lastTick) >= 10)
    {
        if (status.timer_10ms > 0) { status.timer_10ms--; }
        status.lastTick = now;
    }
 
    readKeypad2();
    sCmd.readSerial();
}
