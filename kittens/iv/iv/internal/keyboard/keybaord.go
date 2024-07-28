package keyboard

import (
	"fmt"
	"log"
	"sync"

	"github.com/eiannone/keyboard"
	"iv/internal/navigation"
)

func InitKeyboardHandler() {
	var keyboardWg sync.WaitGroup
	keyboardWg.Add(1)

	go readKeyboardInput(&keyboardWg)
}

func readKeyboardInput(wg *sync.WaitGroup) {
	defer wg.Done()

	if err := keyboard.Open(); err != nil {
		log.Fatal(err)
	}
	defer keyboard.Close()

	fmt.Println("Press 'h' to increment x, 'l' to decrement x, 'j' to increment y, 'k' to decrement y.")
	fmt.Println("Press 'Ctrl+C' to exit.")

	for {
		char, key, err := keyboard.GetSingleKey()
		if err != nil {
			log.Fatal(err)
		}

		switch char {
		case 'h':
			navigation.IncrementX()
		case 'l':
			navigation.DecrementX()
		case 'j':
			navigation.IncrementY()
		case 'k':
			navigation.DecrementY()
		}

		navigation.UpdateImageIndex()

		fmt.Printf("Current navigation parameters: %+v\n", navigation.GetNavigation())

		if key == keyboard.KeyCtrlC {
			break
		}
	}
}
