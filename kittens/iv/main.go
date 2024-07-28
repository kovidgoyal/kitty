package main

import (
	"encoding/base64"
	"fmt"
	"image"
	_ "image/jpeg"
	"image/png"
	_ "image/png"
	"io/fs"
	"log"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/eiannone/keyboard"
	"github.com/nfnt/resize"
	"github.com/spf13/cobra"
	"golang.org/x/sys/unix"
	"gonum.org/v1/gonum/mat"
	"gopkg.in/yaml.v2"
)

func init() {
    globalImageCoordinates = make(map[string][2]int)
}

var rootCmd = &cobra.Command{
	Use:   "icat [directory]",
	Short: "Kitten to display images in a grid layout in Kitty terminal",
	Run:   session,
}

// Will contain all the window parameters
type windowParameters struct {
	Row    uint16
	Col    uint16
	xPixel uint16
	yPixel uint16
}

// Will contain Global Navigation
type navigationParameters struct {
	imageIndex int // Index of the Image selected as per globalImages
    x int          // Horizontal Grid Coordinate
    y int          // Vertical Grid Coordinate
}

// To hold info the image , it's height and width 
type ImageInfo struct {
    Path   string
    Width  int
    Height int
}

// For matrix calculations ,could be useful for more complex image manipulations in the future.
type Matrix2D struct {
    mat *mat.Dense
}

type Config struct {
    GridParam struct {
        XParam int `yaml:"x_param"`
        YParam int `yaml:"y_param"`
    } `yaml:"grid_param"`
}

type ImageBound struct {
	xBound int
	yBound int
}

type ImageCoordinates map[string][2]int

var (
    globalWindowParameters windowParameters // Contains Global Level Window Parameters
    globalConfig Config
    globalNavigation navigationParameters
    globalImages []string
    globalImagePages [][]string
	globalImageBound ImageBound
	globalImageCoordinates ImageCoordinates
)

func xyToIndex(x, y, x_param int) int {
    return y*x_param + x
}

func indexToXY(index, x_param int) (int, int) {
    y := index / x_param
    x := index % x_param
    return x, y
}


/// NOT NEEDED SINCE USING RESIZE METHOD 
// // creates a new 2D matrix
// func NewMatrix2D() *Matrix2D {
//     return &Matrix2D{mat: mat.NewDense(3, 3, nil)}
// }

// // This will set the scale factors for the matrix for transformation later 
// func (m *Matrix2D) Scale(sx, sy float64) {
//     m.mat.Set(0, 0, sx)
//     m.mat.Set(1, 1, sy)
//     m.mat.Set(2, 2, 1)
// }

// //This will set the translation factors for the matrix for transformation later 
// func (m *Matrix2D) Translate(tx, ty float64) {
//     m.mat.Set(0, 2, tx)
//     m.mat.Set(1, 2, ty)
// }

// // applies the transformation to a point
// func (m *Matrix2D) Transform(x, y float64) (float64, float64) {
//     point := mat.NewDense(3, 1, []float64{x, y, 1})
//     result := mat.NewDense(3, 1, nil)
//     result.Mul(m.mat, point)
//     return result.At(0, 0), result.At(1, 0)
// }


//========= CODE FOR FINDING COORDS OF AN IMAGE IN THE GRID (AS PER IT's RESOLUTION)=========

// To retrieve the dimensions of an image
func GetImageInfo(path string) (ImageInfo, error) {
    file, err := os.Open(path)
    if err != nil {
        return ImageInfo{}, err
    }
    defer file.Close()

    img, _, err := image.DecodeConfig(file)
    if err != nil {
        return ImageInfo{}, err
    }

    return ImageInfo{Path: path, Width: img.Width, Height: img.Height}, nil
}


//determines if an image fits in the grid and scales if necessary
func FitImageToGrid(img ImageInfo, gridWidth, gridHeight int) (int, int, bool) {
    if img.Width <= gridWidth && img.Height <= gridHeight {
        return img.Width, img.Height, true
    }

    aspectRatio := float64(img.Width) / float64(img.Height)
    gridRatio := float64(gridWidth) / float64(gridHeight)

    var newWidth, newHeight int
    if aspectRatio > gridRatio {
        newWidth = gridWidth
        newHeight = int(float64(gridWidth) / aspectRatio)
    } else {
        newHeight = gridHeight
        newWidth = int(float64(gridHeight) * aspectRatio)
    }

    return newWidth, newHeight, false
}

// calculates the position to center an image in a grid cell
func CenterImageInGrid(imgWidth, imgHeight, gridWidth, gridHeight int) (int, int) {
    x := (gridWidth - imgWidth) / 2
    y := (gridHeight - imgHeight) / 2
    return x, y
}


//  scales an image to fit the grid and centers it
func ScaleAndCenterImage(img image.Image, gridWidth, gridHeight int) (image.Image, int, int) {
	bounds := img.Bounds()
    imgWidth, imgHeight := bounds.Dx(), bounds.Dy()
    
    newWidth, newHeight, fits := FitImageToGrid(ImageInfo{Width: imgWidth, Height: imgHeight}, gridWidth, gridHeight)
    
    var scaledImg image.Image
    if !fits {
        // Use 0 for one of the dimensions to maintain aspect ratio 
        if float64(newWidth)/float64(imgWidth) < float64(newHeight)/float64(imgHeight) {
            scaledImg = resize.Resize(uint(newWidth), 0, img, resize.Lanczos3)
        } else {
            scaledImg = resize.Resize(0, uint(newHeight), img, resize.Lanczos3)
        }
    } else {
        scaledImg = img
    }
    
    // Recalculate dimensions after scaling
    scaledBounds := scaledImg.Bounds()
    finalWidth, finalHeight := scaledBounds.Dx(), scaledBounds.Dy()
    
    x, y := CenterImageInGrid(finalWidth, finalHeight, gridWidth, gridHeight)
    return scaledImg, x, y
}

//Converts stored coordinates to actual grid positions

// Example calculation:
// Let's assume we have a 3x2 grid layout (3 columns, 2 rows) in a terminal window of 600x400 pixels.
// Our globalImageBound would be calculated as:
//   xBound = 600 / 3 = 200 pixels (width of each grid cell)
//   yBound = 400 / 2 = 200 pixels (height of each grid cell)
//
// Now, let's convert the stored coordinate (1, 1) to its actual position:
//
// Input:
//   x = 1, y = 1
//   globalImageBound.xBound = 200, globalImageBound.yBound = 200
//
// Calculation:
//   actualX = x * globalImageBound.xBound = 1 * 200 = 200
//   actualY = y * globalImageBound.yBound = 1 * 200 = 200
//
// Result:
//   The actual top-left corner of the grid cell for (1, 1) is (200, 200) in pixel coordinates.
//
// This means:
// - (0, 0) would be at (0, 0) in pixels
// - (1, 0) would be at (200, 0) in pixels
// - (2, 0) would be at (400, 0) in pixels
// - (0, 1) would be at (0, 200) in pixels
// - (1, 1) would be at (200, 200) in pixels
// - (2, 1) would be at (400, 200) in pixels

func ConvertToActualGridPosition(x, y int, globalImageBound ImageBound) (int, int) {
    actualX := x * globalImageBound.xBound
    actualY := y * globalImageBound.yBound
    return actualX, actualY
}


// main function to handle image placement
func PlaceImageInGrid(imagePath string, x, y int, globalImageBound ImageBound, globalWindowParameters windowParameters) (image.Image, int, int, error) {
    // Convert stored coordinates to actual grid positions
    actualX, actualY := ConvertToActualGridPosition(x, y, globalImageBound)

    // Get image info
    _, err := GetImageInfo(imagePath)
    if err != nil {
        return nil, 0, 0, err
    }

    // Calculate grid cell dimensions
    gridWidth := int(globalWindowParameters.xPixel) / globalConfig.GridParam.XParam
    gridHeight := int(globalWindowParameters.yPixel) / globalConfig.GridParam.YParam

    // Load the image to get its info
    file, err := os.Open(imagePath)
    if err != nil {
        return nil, 0, 0, err
    }
    defer file.Close()

    img, _, err := image.Decode(file)
    if err != nil {
        return nil, 0, 0, err
    }

    // Scale and center the image
    scaledImg, offsetX, offsetY := ScaleAndCenterImage(img, gridWidth, gridHeight)

    // Calculate the final position using actual grid positions
    finalX := actualX*gridWidth + offsetX
    finalY := actualY*gridHeight + offsetY

    return scaledImg, -finalX, -finalY, nil
}

func debugPrintImage(imagePath string, width, height, x, y int) {
    fmt.Printf("Debug: Image %s (size: %dx%d) placed at position (%d, %d)\n", imagePath, width, height, x, y)
}

// Assign Coordinates to each Image in a Page
//func pageCoordinater() {
//	globalImageBound.xBound = int(globalWindowParameters.Row) / globalConfig.GridParam.XParam
//	globalImageBound.yBound = int(globalWindowParameters.Col) / globalConfig.GridParam.YParam
//
//	for imageIndex, imagePath := range globalImages {
//		x, y := indexToXY(imageIndex, globalConfig.GridParam.XParam)
//		coordinates := [2]int{x, y}
//		globalImageCoordinates[imagePath] = coordinates
//	}
//
//	fmt.Println(globalImageCoordinates)
//}


func pageCoordinater() {

	globalImageBound.xBound = int(globalWindowParameters.Row) / globalConfig.GridParam.XParam
    globalImageBound.yBound = int(globalWindowParameters.Col) / globalConfig.GridParam.YParam

    fmt.Printf("xBound: %d, yBound: %d\n", globalImageBound.xBound, globalImageBound.yBound)
    fmt.Printf("Number of images: %d\n", len(globalImages))

    for imageIndex, imagePath := range globalImages {
        x, y := indexToXY(imageIndex, globalConfig.GridParam.XParam)
        coordinates := [2]int{globalImageBound.xBound * x, globalImageBound.yBound * y}
        globalImageCoordinates[imagePath] = coordinates
    }

    fmt.Println("Final globalImageCoordinates:")
    for path, coord := range globalImageCoordinates {
        fmt.Printf("%s: (%d, %d)\n", path, coord[0], coord[1])
    }
}

func pageCoordinater2() {

	fmt.Printf("globalWindowParameters.Row: %d\n", globalWindowParameters.Row)
    fmt.Printf("globalWindowParameters.Col: %d\n", globalWindowParameters.Col)
    fmt.Printf("globalConfig.GridParam.XParam: %d\n", globalConfig.GridParam.XParam)
    fmt.Printf("globalConfig.GridParam.YParam: %d\n", globalConfig.GridParam.YParam)

    globalImageBound.xBound = int(globalWindowParameters.Row) / globalConfig.GridParam.XParam
    globalImageBound.yBound = int(globalWindowParameters.Col) / globalConfig.GridParam.YParam

    fmt.Printf("xBound: %d, yBound: %d\n", globalImageBound.xBound, globalImageBound.yBound)
    fmt.Printf("Number of images: %d\n", len(globalImages))
    fmt.Printf("XParam: %d\n", globalConfig.GridParam.XParam)

    for imageIndex, imagePath := range globalImages {
        x, y := indexToXY(imageIndex, globalConfig.GridParam.XParam)
        fmt.Printf("Before multiplication - imageIndex: %d, x: %d, y: %d\n", imageIndex, x, y)

        coordinates := [2]int{globalImageBound.xBound * x, globalImageBound.yBound * y}
        globalImageCoordinates[imagePath] = coordinates

        fmt.Printf("After multiplication - imagePath: %s, coordinates: (%d, %d)\n", imagePath, coordinates[0], coordinates[1])
    }

    fmt.Println("Final globalImageCoordinates:")
    for path, coord := range globalImageCoordinates {
        fmt.Printf("%s: (%d, %d)\n", path, coord[0], coord[1])
    }
}

// This function takes globalConfig struct and parses the YAML data
func loadConfig(filename string) error {
    data, err := os.ReadFile(filename)
    if err != nil {
        log.Printf("Error reading file: %v", err)
        return err
    }

    err = yaml.Unmarshal(data, &globalConfig)
    if err != nil {
        log.Printf("Error unmarshaling YAML: %v", err)
        return err
    }

    return nil
}

// Gets the window size and modifies the globalWindowParameters (global struct)
func getWindowSize(window windowParameters) error {
	var err error
	var f *os.File

	// Read the window size from device drivers and print them
	if f, err = os.OpenFile("/dev/tty", unix.O_NOCTTY|unix.O_CLOEXEC|unix.O_NDELAY|unix.O_RDWR, 0666); err == nil {
		var sz *unix.Winsize
		if sz, err = unix.IoctlGetWinsize(int(f.Fd()), unix.TIOCGWINSZ); err == nil {
			fmt.Printf("rows: %v columns: %v width: %v height %v\n", sz.Row, sz.Col, sz.Xpixel, sz.Ypixel)
			window.Row = sz.Row
			window.Col = sz.Col
			window.xPixel = sz.Xpixel
			window.yPixel = sz.Ypixel
			return nil
		}
	}

	fmt.Fprintln(os.Stderr, err)
	// os.Exit(1)

    return err
}

// Function handler for changes in window sizes (will be added to goroutines)
func handleWindowSizeChange() {
	err := getWindowSize(globalWindowParameters)
	if err != nil {
		fmt.Println("Error getting window size:", err)
	}
}

// Checks if a given file is an image
func isImage(fileName string) bool {
	extensions := []string{".jpg", ".jpeg", ".png", ".gif", ".bmp"}
	ext := strings.ToLower(filepath.Ext(fileName))
	for _, e := range extensions {
		if ext == e {
			return true
		}
	}
	return false
}

// findImages recursively searches for image files in the given directory
func discoverImages(dir string) error {
	err := filepath.WalkDir(dir, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if !d.IsDir() && isImage(d.Name()) {
			globalImages = append(globalImages, path)
		}
		return nil
	})
	if err != nil {
		return fmt.Errorf("error walking directory: %w", err)
	}
	return nil
}

// Resizes images, return
func resizeImage(img image.Image, width, height uint) image.Image {
    return resize.Resize(width, height, img, resize.Lanczos3)
}

func imageToBase64(img image.Image) (string, error) {
    var buf strings.Builder
    err := png.Encode(&buf, img)
    if err != nil {
        return "", err
    }
    encoded := base64.StdEncoding.EncodeToString([]byte(buf.String()))
    return encoded, nil
}

func loadImage(filePath string) (image.Image, error) {
    file, err := os.Open(filePath)
    if err != nil {
        return nil, err
    }
    defer file.Close()

    img, _, err := image.Decode(file)
    if err != nil {
        return nil, err
    }
    return img, nil
}

// Print image to Kitty Terminal
func printImageToKitty(encoded string, width, height int) {
    fmt.Printf("\x1b_Gf=1,t=%d,%d;x=%s\x1b\\", width, height, encoded)
}

func readKeyboardInput(navParams *navigationParameters, wg *sync.WaitGroup) {
	defer wg.Done()

	// Open the keyboard
	if err := keyboard.Open(); err != nil {
		log.Fatal(err)
	}
	defer keyboard.Close()

	fmt.Println("Press 'h' to increment x, 'l' to decrement x, 'j' to increment y, 'k' to decrement y.")
	fmt.Println("Press 'Ctrl+C' to exit.")

	for {
		// Read the key event
		char, key, err := keyboard.GetSingleKey()
		if err != nil {
			log.Fatal(err)
		}

		// Handle the key event
		switch char {
		case 'h':
			if (navParams.x > 0) {
				navParams.x--
			}
		case 'l':
			navParams.x++
		case 'j':
			navParams.y++
		case 'k':
            if (navParams.y > 0) { // cursor is at the top most part of the screen
			    navParams.y--
		    }
        }

		// Update the image index which locates the image index to
		navParams.imageIndex = xyToIndex(navParams.x, navParams.y, globalConfig.GridParam.XParam)

		// Print the current state of navigation parameters
		fmt.Printf("Current navigation parameters (in goroutine): %+v\n", *navParams)

		// Exit the loop if 'Ctrl+C' is pressed
		if key == keyboard.KeyCtrlC {
			break
		}
    var xParam int = globalConfig.GridParam.XParam
    var yParam int = globalConfig.GridParam.YParam

    for i := 0; i < len(globalImages); i += xParam {
        end := i + xParam
        if end > len(globalImages) {
            end = len(globalImages)
        }

        row := globalImages[i:end]
        globalImagePages = append(globalImagePages, row)

        if len(globalImagePages) == yParam {
            break
        }
    }
}

// Routine for session - kitten will run in this space
func session(cmd *cobra.Command, args []string) {

	// Check for Arguements
	if len(args) == 0 {
		fmt.Println("Please specify a directory")
		os.Exit(1)
	}

	// Get directory name and discover images
	dir := args[0]
	err := discoverImages(dir)
	if err != nil {
		fmt.Printf("Error discovering images: %v\n", err)
		os.Exit(1)
	}

	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, syscall.SIGWINCH)

	// Get the window size initially when kitten is spawned
	handleWindowSizeChange()

	// Goroutine to listen for window size changes
	go func() {
		for {
			sig := <-sigs

            // if window size change syscall is detected, execute the handleWindowSizeChange()
			if sig == syscall.SIGWINCH {
				handleWindowSizeChange()
			}
		}
	}()

    /* Getting Keyboard Inputs into Goroutines
    Here, the keyboard handler with keep updating the globalNavigation and update x and y.
    globalNavigation contains all the global cooridinates, updated regularly and keeps the whole
    program aware of current state of keyboard.
    */

    var keyboardWg sync.WaitGroup
    keyboardWg.Add(1)

    go readKeyboardInput(&globalNavigation, &keyboardWg)

    // Till this point, WindowSize Changes would be handled and stored into globalWindowParameters

    /* Load system configuration from kitty.conf
    Currently, the loadConfig is loading configurations from config.yaml, parsing can be updated later
    */
    err = loadConfig("./config.yaml")
    if (err != nil) {
        fmt.Printf("Error Parsing config file, exiting ....")
        os.Exit(1)
    }

	// globalConfig.GridParam.XParam = 3
	// globalConfig.GridParam.YParam = 2
	fmt.Printf("Window parameters: X = %d, Y = %d\n",
               globalConfig.GridParam.XParam,
               globalConfig.GridParam.YParam)

    // if x_param or y_param are 0, exit
    if (globalConfig.GridParam.XParam == 0 || globalConfig.GridParam.YParam == 0) {
        fmt.Printf("x_param or y_param set to 0, check the system config file for kitty")
        os.Exit(1)
    }


	pageCoordinater()


	for imagePath, coordinates := range globalImageCoordinates {
        x, y := coordinates[0], coordinates[1]
        img, posX, posY, err := PlaceImageInGrid(imagePath, x, y, globalImageBound, globalWindowParameters)
        if err != nil {
            fmt.Printf("Error processing image %s: %v\n", imagePath, err)
            continue
        }
        bounds := img.Bounds()
        debugPrintImage(imagePath, bounds.Dx(), bounds.Dy(), posX, posY)
    }


	time.Sleep(100 * time.Second)

}

func main() {

	if err := rootCmd.Execute(); err != nil {
		fmt.Println(err)
		os.Exit(1)
	}
}
