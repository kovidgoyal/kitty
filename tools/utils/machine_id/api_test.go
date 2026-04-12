package machine_id

import (
	"fmt"
	"testing"
)

var _ = fmt.Print

func TestMachineId(t *testing.T) {
	_, err := MachineId()
	if err != nil {
		t.Fatal(err)
	}
}
