// License: GPLv3 Copyright: 2024, Kovid Goyal, <kovid at kovidgoyal.net>

package images

/*
#cgo pkg-config: libjxl libjxl_threads
#include <stdlib.h>
#include <string.h>
#include <jxl/decode.h>
#include <jxl/thread_parallel_runner.h>

typedef struct {
    unsigned char *data;
    size_t size;
    uint32_t width;
    uint32_t height;
    char *error;
} JxlDecodeResult;

static JxlDecodeResult decode_jxl(const unsigned char *input, size_t input_size) {
    JxlDecodeResult result = {0};
    JxlDecoder *dec = NULL;
    void *runner = NULL;
    JxlBasicInfo info;
    JxlPixelFormat format = {4, JXL_TYPE_UINT8, JXL_NATIVE_ENDIAN, 0};

    dec = JxlDecoderCreate(NULL);
    if (!dec) {
        result.error = strdup("Failed to create JXL decoder");
        goto cleanup;
    }

    runner = JxlThreadParallelRunnerCreate(NULL, JxlThreadParallelRunnerDefaultNumWorkerThreads());
    if (!runner) {
        result.error = strdup("Failed to create JXL parallel runner");
        goto cleanup;
    }

    if (JxlDecoderSetParallelRunner(dec, JxlThreadParallelRunner, runner) != JXL_DEC_SUCCESS) {
        result.error = strdup("Failed to set JXL parallel runner");
        goto cleanup;
    }

    if (JxlDecoderSubscribeEvents(dec, JXL_DEC_BASIC_INFO | JXL_DEC_FULL_IMAGE) != JXL_DEC_SUCCESS) {
        result.error = strdup("Failed to subscribe to JXL events");
        goto cleanup;
    }

    if (JxlDecoderSetInput(dec, input, input_size) != JXL_DEC_SUCCESS) {
        result.error = strdup("Failed to set JXL input");
        goto cleanup;
    }
    JxlDecoderCloseInput(dec);

    JxlDecoderStatus status;
    while ((status = JxlDecoderProcessInput(dec)) != JXL_DEC_SUCCESS) {
        switch (status) {
            case JXL_DEC_ERROR:
                result.error = strdup("JXL decoding error");
                goto cleanup;
            case JXL_DEC_NEED_MORE_INPUT:
                result.error = strdup("JXL decoder needs more input (incomplete file?)");
                goto cleanup;
            case JXL_DEC_BASIC_INFO:
                if (JxlDecoderGetBasicInfo(dec, &info) != JXL_DEC_SUCCESS) {
                    result.error = strdup("Failed to get JXL basic info");
                    goto cleanup;
                }
                result.width = info.xsize;
                result.height = info.ysize;
                break;
            case JXL_DEC_NEED_IMAGE_OUT_BUFFER: {
                size_t buffer_size;
                if (JxlDecoderImageOutBufferSize(dec, &format, &buffer_size) != JXL_DEC_SUCCESS) {
                    result.error = strdup("Failed to get JXL output buffer size");
                    goto cleanup;
                }
                result.size = buffer_size;
                result.data = (unsigned char *)malloc(buffer_size);
                if (!result.data) {
                    result.error = strdup("Out of memory allocating JXL output buffer");
                    goto cleanup;
                }
                if (JxlDecoderSetImageOutBuffer(dec, &format, result.data, result.size) != JXL_DEC_SUCCESS) {
                    result.error = strdup("Failed to set JXL output buffer");
                    goto cleanup;
                }
                break;
            }
            case JXL_DEC_FULL_IMAGE:
                // Image is ready
                break;
            default:
                // Continue processing
                break;
        }
    }

cleanup:
    if (runner) JxlThreadParallelRunnerDestroy(runner);
    if (dec) JxlDecoderDestroy(dec);
    if (result.error && result.data) {
        free(result.data);
        result.data = NULL;
    }
    return result;
}

static void free_jxl_result(JxlDecodeResult *result) {
    if (result->data) {
        free(result->data);
        result->data = NULL;
    }
    if (result->error) {
        free(result->error);
        result->error = NULL;
    }
}
*/
import "C"

import (
	"fmt"
	"image"
	"io"
	"unsafe"
)

func init() {
	image.RegisterFormat("jxl", "\xff\x0a", DecodeJXL, DecodeJXLConfig)
	// Also register the container format signature
	image.RegisterFormat("jxl", "\x00\x00\x00\x0cJXL ", DecodeJXL, DecodeJXLConfig)
}

// DecodeJXL decodes a JXL image from the given reader
func DecodeJXL(r io.Reader) (image.Image, error) {
	data, err := io.ReadAll(r)
	if err != nil {
		return nil, fmt.Errorf("failed to read JXL data: %w", err)
	}

	if len(data) == 0 {
		return nil, fmt.Errorf("empty JXL data")
	}

	cData := C.CBytes(data)
	defer C.free(cData)

	result := C.decode_jxl((*C.uchar)(cData), C.size_t(len(data)))
	defer C.free_jxl_result(&result)

	if result.error != nil {
		return nil, fmt.Errorf("JXL decode error: %s", C.GoString(result.error))
	}

	width := int(result.width)
	height := int(result.height)

	if width <= 0 || height <= 0 {
		return nil, fmt.Errorf("invalid JXL dimensions: %dx%d", width, height)
	}

	// Copy the pixel data to Go memory
	pixelData := C.GoBytes(unsafe.Pointer(result.data), C.int(result.size))

	// Create an NRGBA image from the RGBA data
	img := image.NewNRGBA(image.Rect(0, 0, width, height))
	copy(img.Pix, pixelData)

	return img, nil
}

// DecodeJXLConfig returns the color model and dimensions of a JXL image
func DecodeJXLConfig(r io.Reader) (image.Config, error) {
	// For config, we need to decode the full image unfortunately
	// as libjxl doesn't have a separate header-only decode
	img, err := DecodeJXL(r)
	if err != nil {
		return image.Config{}, err
	}
	bounds := img.Bounds()
	return image.Config{
		ColorModel: img.ColorModel(),
		Width:      bounds.Dx(),
		Height:     bounds.Dy(),
	}, nil
}
