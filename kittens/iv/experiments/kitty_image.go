package main

import (
	"bufio"
	"encoding/base64"
	"fmt"
	"os"
	"path/filepath"
)

func writeChunk(writer *bufio.Writer, data []byte) {
	encoded := base64.StdEncoding.EncodeToString(data)
	writer.WriteString(encoded)
	writer.WriteByte('\n')
}

func writeImageFile(writer *bufio.Writer, filename string) error {
	extension := filepath.Ext(filename)
	mimeType := "image/png"
	if extension == ".jpg" || extension == ".jpeg" {
		mimeType = "image/jpeg"
	}

	file, err := os.Open(filename)
	if err != nil {
		return err
	}
	defer file.Close()

	fileInfo, err := file.Stat()
	if err != nil {
		return err
	}
	fileSize := fileInfo.Size()

	fmt.Fprintf(writer, "\033_Gf=100,s=%d,v=0,m=1;%s\033\\", fileSize, mimeType)
	writer.Flush()

	chunk := make([]byte, 4096)
	for {
		bytesRead, err := file.Read(chunk)
		if err != nil {
			if err.Error() == "EOF" {
				break
			}
			return err
		}
		if bytesRead > 0 {
			fmt.Fprint(writer, "\033_Gm=1;")
			writeChunk(writer, chunk[:bytesRead])
			fmt.Fprint(writer, "\033\\")
			writer.Flush()
		}
	}

	fmt.Fprint(writer, "\033_Gm=0;\033\\")
	writer.Flush()
	return nil
}

func main() {
	if len(os.Args) < 2 {
		fmt.Println("Please provide an image filename")
		os.Exit(1)
	}

	filename := os.Args[1]
	writer := bufio.NewWriter(os.Stdout)
	err := writeImageFile(writer, filename)
	if err != nil {
		fmt.Println("Error:", err)
		os.Exit(1)
	}
}
