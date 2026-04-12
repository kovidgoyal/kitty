package machine_id

import (
	"fmt"
	"sync"
)

var _ = fmt.Print

var MachineId = sync.OnceValues(read_machine_id)
