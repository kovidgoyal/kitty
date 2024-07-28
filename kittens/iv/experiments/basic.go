package main

import (
	"encoding/base64"
	"fmt"
	"io"
	"os"
)

func serializeGRCommand(cmd map[string]string, payload []byte) []byte {
	cmdStr := ""
	for k, v := range cmd {
		cmdStr += fmt.Sprintf("%s=%s,", k, v)
	}
	// Remove trailing comma
	if len(cmdStr) > 0 {
		cmdStr = cmdStr[:len(cmdStr)-1]
	}

	ans := []byte("\033_G" + cmdStr)
	if payload != nil {
		ans = append(ans, ';')
		ans = append(ans, payload...)
	}
	ans = append(ans, []byte("\033\\")...)
	return ans
}

func writeChunked(imagePath string) error {
	file, err := os.Open(imagePath)
	if err != nil {
		return fmt.Errorf("error opening file: %v", err)
	}
	defer file.Close()

	data := make([]byte, 4096)
	for {
		n, err := file.Read(data)
		if err != nil && err != io.EOF {
			return fmt.Errorf("error reading file: %v", err)
		}
		if n == 0 {
			break
		}

		encoded := make([]byte, base64.StdEncoding.EncodedLen(n))
		base64.StdEncoding.Encode(encoded, data[:n])
		chunk := encoded

		cmd := map[string]string{
			"a": "T",
			"f": "100",
		}
		if n < len(data) {
			cmd["m"] = "0"
		} else {
			cmd["m"] = "1"
		}

		serializedCmd := serializeGRCommand(cmd, chunk)
		if _, err := os.Stdout.Write(serializedCmd); err != nil {
			return fmt.Errorf("error writing to stdout: %v", err)
		}
		os.Stdout.Sync()

		if n < len(data) {
			break
		}
	}

	return nil
}

func main() {
	err := writeChunked("../../../logo/kitty.png")
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
	}
}
