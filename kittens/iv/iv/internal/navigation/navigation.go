package navigation

import "iv/internal/config"

type NavigationParameters struct {
	ImageIndex int
	X          int
	Y          int
}

var globalNavigation NavigationParameters

func GetNavigation() NavigationParameters {
	return globalNavigation
}

func IncrementX() {
	globalNavigation.X++
}

func DecrementX() {
	if globalNavigation.X > 0 {
		globalNavigation.X--
	}
}

func IncrementY() {
	globalNavigation.Y++
}

func DecrementY() {
	if globalNavigation.Y > 0 {
		globalNavigation.Y--
	}
}

func UpdateImageIndex() {
	globalNavigation.ImageIndex = XYToIndex(globalNavigation.X, globalNavigation.Y, config.GetConfig().GridParam.XParam)
}

func XYToIndex(x, y, xParam int) int {
	return y*xParam + x
}

func IndexToXY(index, xParam int) (int, int) {
	y := index / xParam
	x := index % xParam
	return x, y
}
