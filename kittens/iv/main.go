package main

import (
	"encoding/base64"
	"fmt"
	"image"
	"image/png"
	"log"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
    "io/fs"

	"github.com/eiannone/keyboard"
	"github.com/nfnt/resize"
	"github.com/spf13/cobra"
	"golang.org/x/sys/unix"
	"gopkg.in/yaml.v2"
)

var rootCmd = &cobra.Command{
	Use:   "icat [directory]",
	Short: "Kitten to display images in a grid layout in Kitty terminal",
	Run:   session,
}

type gridConfig struct {
    x_param int `yaml:"xParam"`    // horizontal parameter  
    y_param int `yaml:"yParam"`    // vertical parameter 
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
    x int          // Horizontal Grid Coordinate 
    y int          // Vertical Grid Coordinate 
}

// Config struct to hold the configuration
type Config struct {
    gridParam gridConfig `yaml:"windowParam"`
}

var (
    globalWindowParameters windowParameters // Contains Global Level Window Parameters 
    globalConfig Config
    globalNavigation navigationParameters
    globalImages []string 
    globalImagePages [][]string 
)

// This function takes globalConfig struct and parses the YAML data 
func loadConfig(filename string) error {
    data, err := os.ReadFile(filename)
    if err != nil {
        log.Fatalf("error: %v", err)
        return err
    }
    
    err = yaml.Unmarshal(data, &globalConfig)
    if err != nil {
        log.Fatalf("error: %v", err)
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
			navParams.x++
		case 'l':
            if (navParams.x > 0) { // cursor is at left most part of the screen 
			    navParams.x--
            }
		case 'j':
			navParams.y++
		case 'k':
            if (navParams.y > 0) { // cursor is at the top most part of the screen  
			    navParams.y--
		    }
        }

		// Print the current state of navigation parameters
		fmt.Printf("Current navigation parameters (in goroutine): %+v\n", *navParams)

		// Exit the loop if 'Ctrl+C' is pressed
		if key == keyboard.KeyCtrlC {
			break
		}
	}
}

// Paginate images into slice called globalImagePages from globalImages
func paginateImages() {
    var xParam int = globalConfig.gridParam.x_param
    var yParam int = globalConfig.gridParam.y_param

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
  
    var config Config

    /* Load system configuration from kitty.conf
    Currently, the loadConfig is loading configurations from config.yaml, parsing can be updated later 
    */ 
    err = loadConfig("config.yaml")
    if (err != nil) {
        fmt.Printf("Error Parsing config file, exiting ....")
        os.Exit(1)
    }
   
    // if x_param or y_param are 0, exit 
    if (config.gridParam.x_param == 0 || config.gridParam.y_param == 0) {
        fmt.Printf("x_param or y_param set to 0, check the system config file for kitty")
        os.Exit(1)
    }

    // config cannot be changed at runtime 
	//err = renderImageGrid(images, gridConfig)
	//if err != nil {
	//	fmt.Printf("Error rendering image grid: %v\n", err)
	//	os.Exit(1)
	//}

	//err = handleNavigation(images, layout)
	//if err != nil {
	//	fmt.Printf("Error during navigation: %v\n", err)
	//	os.Exit(1)
	//}
}

func main() {

	if err := rootCmd.Execute(); err != nil {
		fmt.Println(err)
		os.Exit(1)
	}
}
