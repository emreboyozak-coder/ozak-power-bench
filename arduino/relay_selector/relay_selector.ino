/*
 * Five-slot DC/DC bench relay selector.
 * Serial protocol at 9600 baud: send five bits for pins 2,3,4,5,6.
 * Example: 00100 sets pin 4 HIGH and all other relay pins LOW.
 * 00000 turns all relay outputs off. Replies: OK <mask> or ERR.
 *
 * Connect one relay-module input to each pin 2..6. Set RELAY_ACTIVE_HIGH to
 * false if the relay board is active LOW. Keep PSU output
 * disabled while changing slots (the Python controller does this).
 */
const byte RELAY_PINS[5] = {2, 3, 4, 5, 6};
const bool RELAY_ACTIVE_HIGH = true;
String commandBuffer;

void setRelay(byte index, bool enabled) {
  const byte onLevel = RELAY_ACTIVE_HIGH ? HIGH : LOW;
  const byte offLevel = RELAY_ACTIVE_HIGH ? LOW : HIGH;
  digitalWrite(RELAY_PINS[index], enabled ? onLevel : offLevel);
}

void allOff() {
  for (byte i = 0; i < 5; i++) setRelay(i, false);
}

void setup() {
  for (byte i = 0; i < 5; i++) {
    digitalWrite(RELAY_PINS[i], RELAY_ACTIVE_HIGH ? LOW : HIGH);
    pinMode(RELAY_PINS[i], OUTPUT);
  }
  allOff();
  Serial.begin(9600);
}

void handleCommand(String command) {
  command.trim();
  command.toUpperCase();
  if (command.length() == 5) {
    byte selectedCount = 0;
    for (byte i = 0; i < 5; i++) {
      if (command[i] != '0' && command[i] != '1') {
        allOff();
        Serial.println("ERR");
        return;
      }
      if (command[i] == '1') selectedCount++;
    }
    if (selectedCount > 1) {
      allOff();
      Serial.println("ERR");
      return;
    }
    allOff();
    delay(1000);  // Allow the previous relay contacts to release before switching.
    for (byte i = 0; i < 5; i++) setRelay(i, command[i] == '1');
    Serial.print("OK ");
    Serial.println(command);
    return;
  }
  Serial.println("ERR");
}

void loop() {
  while (Serial.available()) {
    char ch = (char)Serial.read();
    if (ch == '\n') {
      handleCommand(commandBuffer);
      commandBuffer = "";
    } else if (ch != '\r' && commandBuffer.length() < 32) {
      commandBuffer += ch;
    }
  }
}
