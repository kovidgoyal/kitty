package main

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
	"iv/internal/config"
	"iv/internal/image"
	"iv/internal/keyboard"
	//"iv/internal/navigation"
	"iv/internal/window"
)

var rootCmd = &cobra.Command{
	Use:   "iv [directory]",
	Short: "Display images in a grid layout in Kitty terminal",
	Run:   session,
}

func session(cmd *cobra.Command, args []string) {
	// Check for Arguments
	if len(args) == 0 {
		fmt.Println("Please specify a directory")
		os.Exit(1)
	}

	// Get directory name and discover images
	dir := args[0]
	err := image.DiscoverImages(dir)
	if err != nil {
		fmt.Printf("Error discovering images: %v\n", err)
		os.Exit(1)
	}

	// Initialize window size handler
	window.InitWindowSizeHandler()

	// Initialize keyboard handler
	keyboard.InitKeyboardHandler()

	// Load configuration
	err = config.LoadConfig("config.yaml")
	if err != nil {
		fmt.Printf("Error Parsing config file, exiting ....")
		os.Exit(1)
	}

	// Check configuration
	if config.GetConfig().GridParam.XParam == 0 || config.GetConfig().GridParam.YParam == 0 {
		fmt.Printf("x_param or y_param set to 0, check the system config file for kitty")
		os.Exit(1)
	}

	// Additional session logic here...
}

func main() {
	if err := rootCmd.Execute(); err != nil {
		fmt.Println(err)
		os.Exit(1)
	}
}
