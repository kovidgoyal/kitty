package config

import (
	"os"

	"gopkg.in/yaml.v2"
)

type GridConfig struct {
	XParam int `yaml:"xParam"`
	YParam int `yaml:"yParam"`
}

type Config struct {
	GridParam GridConfig `yaml:"windowParam"`
}

var globalConfig Config

func LoadConfig(filename string) error {
	data, err := os.ReadFile(filename)
	if err != nil {
		return err
	}

	err = yaml.Unmarshal(data, &globalConfig)
	if err != nil {
		return err
	}

	return nil
}

func GetConfig() Config {
	return globalConfig
}
