#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>

import json
import posixpath
import sys
from collections import namedtuple
from datetime import datetime
from enum import Enum
from functools import cached_property
from typing import IO, List, Mapping, Optional

Frame = namedtuple('Frame', 'image_name image_base image_offset symbol symbol_offset')
Register = namedtuple('Register', 'name value')


def surround(x: str, start: int, end: int) -> str:
    if sys.stdout.isatty():
        x = f'\033[{start}m{x}\033[{end}m'
    return x


def cyan(x: str) -> str:
    return surround(x, 96, 39)


def bold(x: str) -> str:
    return surround(x, 1, 22)


class BugType(Enum):
    WatchdogTimeout = '28'
    BasebandStats = '195'
    GPUEvent = '284'
    Sandbox = '187'
    TerminatingStackshot = '509'
    ServiceWatchdogTimeout = '29'
    Session = '179'
    LegacyStackshot = '188'
    MACorrelation = '197'
    iMessages = '189'
    log_power = '278'
    PowerLog = 'powerlog'
    DuetKnowledgeCollector2 = '58'
    BridgeRestore = '83'
    LegacyJetsam = '198'
    ExcResource_385 = '385'
    Modem = '199'
    Stackshot = '288'
    SystemInformation = 'system_profile'
    Jetsam_298 = '298'
    MemoryResource = '30'
    Bridge = '31'
    DifferentialPrivacy = 'diff_privacy'
    FirmwareIntegrity = '32'
    CoreAnalytics_33 = '33'
    AutoBugCapture = '34'
    EfiFirmwareIntegrity = '35'
    SystemStats = '36'
    AnonSystemStats = '37'
    Crash_9 = '9'
    Jetsam_98 = '98'
    LDCM = '100'
    Panic_10 = '10'
    Spin = '11'
    CLTM = '101'
    Hang = '12'
    Panic_110 = '110'
    ConnectionFailure = '13'
    MessageTracer = '14'
    LowBattery = '120'
    Siri = '201'
    ShutdownStall = '17'
    Panic_210 = '210'
    SymptomsCPUUsage = '202'
    AssumptionViolation = '18'
    CoreHandwriting = 'chw'
    IOMicroStackShot = '44'
    CoreAnalytics_211 = '211'
    SiriAppPrediction = '203'
    spin_45 = '45'
    PowerMicroStackshots = '220'
    BTMetadata = '212'
    SystemMemoryReset = '301'
    ResetCount = '115'
    AutoBugCapture_204 = '204'
    WifiCrashBinary = '221'
    MicroRunloopHang = '310'
    Rosetta = '213'
    glitchyspin = '302'
    System = '116'
    IOPowerSources = '141'
    PanicStats = '205'
    PowerLog_230 = '230'
    LongRunloopHang = '222'
    HomeProductsAnalytics = '311'
    DifferentialPrivacy_150 = '150'
    Rhodes = '214'
    ProactiveEventTrackerTransparency = '303'
    WiFi = '117'
    SymptomsCPUWakes = '142'
    SymptomsCPUUsageFatal = '206'
    Crash_109 = '109'
    ShortRunloopHang = '223'
    CoreHandwriting_231 = '231'
    ForceReset = '151'
    SiriAppSelection = '215'
    PrivateFederatedLearning = '304'
    Bluetooth = '118'
    SCPMotion = '143'
    HangSpin = '207'
    StepCount = '160'
    RTCTransparency = '224'
    DiagnosticRequest = '312'
    MemorySnapshot = '152'
    Rosetta_B = '216'
    AudioAccessory = '305'
    General = '119'
    HotSpotIOMicroSS = '144'
    GeoServicesTransparency = '233'
    MotionState = '161'
    AppStoreTransparency = '225'
    SiriSearchFeedback = '313'
    BearTrapReserved = '153'
    Portrait = '217'
    AWDMetricLog = 'metriclog'
    SymptomsIO = '145'
    SubmissionReserved = '170'
    WifiCrash = '209'
    Natalies = '162'
    SecurityTransparency = '226'
    BiomeMapReduce = '234'
    MemoryGraph = '154'
    MultichannelAudio = '218'
    honeybee_payload = '146'
    MesaReserved = '171'
    WifiSensing = '235'
    SiriMiss = '163'
    ExcResourceThreads_227 = '227'
    TestA = 'T01'
    NetworkUsage = '155'
    WifiReserved = '180'
    SiriActionPrediction = '219'
    honeybee_heartbeat = '147'
    ECCEvent = '172'
    KeyTransparency = '236'
    SubDiagHeartBeat = '164'
    ThirdPartyHang = '228'
    OSFault = '308'
    CoreTime = '156'
    WifiDriverReserved = '181'
    Crash_309 = '309'
    honeybee_issue = '148'
    CellularPerfReserved = '173'
    TestB = 'T02'
    StorageStatus = '165'
    SiriNotificationTransparency = '229'
    TestC = 'T03'
    CPUMicroSS = '157'
    AccessoryUpdate = '182'
    xprotect = '20'
    MultitouchFirmware = '149'
    MicroStackshot = '174'
    AppLaunchDiagnostics = '238'
    KeyboardAccuracy = '166'
    GPURestart = '21'
    FaceTime = '191'
    DuetKnowledgeCollector = '158'
    OTASUpdate = '183'
    ExcResourceThreads_327 = '327'
    ExcResource_22 = '22'
    DuetDB = '175'
    ThirdPartyHangDeveloper = '328'
    PrivacySettings = '167'
    GasGauge = '192'
    MicroStackShots = '23'
    BasebandCrash = '159'
    GPURestart_184 = '184'
    SystemWatchdogCrash = '409'
    FlashStatus = '176'
    SleepWakeFailure = '24'
    CarouselEvent = '168'
    AggregateD = '193'
    WakeupsMonitorViolation = '25'
    DifferentialPrivacy_50 = '50'
    ExcResource_185 = '185'
    UIAutomation = '177'
    ping = '26'
    SiriTransaction = '169'
    SURestore = '194'
    KtraceStackshot = '186'
    WirelessDiagnostics = '27'
    PowerLogLite = '178'
    SKAdNetworkAnalytics = '237'
    HangWorkflowResponsiveness = '239'
    CompositorClientHang = '243'


class CrashReportBase:
    def __init__(self, metadata: Mapping, data: str, filename: str = None):
        self.filename = filename
        self._metadata = metadata
        self._data = data
        self._parse()

    def _parse(self):
        self._is_json = False
        try:
            modified_data = self._data
            if '\n  \n' in modified_data:
                modified_data, rest = modified_data.split('\n  \n', 1)
                rest = '",' + rest.split('",', 1)[1]
                modified_data += rest
            self._data = json.loads(modified_data)
            self._is_json = True
        except json.decoder.JSONDecodeError:
            pass

    @cached_property
    def bug_type(self) -> BugType:
        return BugType(self.bug_type_str)

    @cached_property
    def bug_type_str(self) -> str:
        return self._metadata['bug_type']

    @cached_property
    def incident_id(self):
        return self._metadata.get('incident_id')

    @cached_property
    def timestamp(self) -> datetime:
        timestamp = self._metadata.get('timestamp')
        timestamp_without_timezone = timestamp.rsplit(' ', 1)[0]
        return datetime.strptime(timestamp_without_timezone, '%Y-%m-%d %H:%M:%S.%f')

    @cached_property
    def name(self) -> str:
        return self._metadata.get('name')

    def __repr__(self) -> str:
        filename = ''
        if self.filename:
            filename = f'FILENAME:{posixpath.basename(self.filename)} '
        return f'<{self.__class__} {filename}TIMESTAMP:{self.timestamp}>'

    def __str__(self) -> str:
        filename = ''
        if self.filename:
            filename = self.filename

        return cyan(f'{self.incident_id} {self.timestamp}\n{filename}\n\n')


class UserModeCrashReport(CrashReportBase):
    def _parse_field(self, name: str) -> str:
        name += ':'
        for line in self._data.split('\n'):
            if line.startswith(name):
                field = line.split(name, 1)[1]
                field = field.strip()
                return field

    @cached_property
    def faulting_thread(self) -> int:
        if self._is_json:
            return self._data['faultingThread']
        else:
            return int(self._parse_field('Triggered by Thread'))

    @cached_property
    def frames(self) -> List[Frame]:
        result = []
        if self._is_json:
            thread_index = self.faulting_thread
            images = self._data['usedImages']
            for frame in self._data['threads'][thread_index]['frames']:
                image = images[frame['imageIndex']]
                result.append(
                    Frame(image_name=image.get('path'), image_base=image.get('base'), symbol=frame.get('symbol'),
                          image_offset=frame.get('imageOffset'), symbol_offset=frame.get('symbolLocation')))
        else:
            in_frames = False
            for line in self._data.split('\n'):
                if in_frames:
                    splitted = line.split()

                    if len(splitted) == 0:
                        break

                    assert splitted[-2] == '+'
                    image_base = splitted[-3]
                    if image_base.startswith('0x'):
                        result.append(Frame(image_name=splitted[1], image_base=int(image_base, 16), symbol=None,
                                            image_offset=int(splitted[-1]), symbol_offset=None))
                    else:
                        # symbolicated
                        result.append(Frame(image_name=splitted[1], image_base=None, symbol=image_base,
                                            image_offset=None, symbol_offset=int(splitted[-1])))

                if line.startswith(f'Thread {self.faulting_thread} Crashed:'):
                    in_frames = True

        return result

    @cached_property
    def registers(self) -> List[Register]:
        result = []
        if self._is_json:
            thread_index = self._data['faultingThread']
            thread_state = self._data['threads'][thread_index]['threadState']

            if 'x' in thread_state:
                for i, reg_x in enumerate(thread_state['x']):
                    result.append(Register(name=f'x{i}', value=reg_x['value']))

            for i, (name, value) in enumerate(thread_state.items()):
                if name == 'x':
                    for j, reg_x in enumerate(value):
                        result.append(Register(name=f'x{j}', value=reg_x['value']))
                else:
                    if isinstance(value, dict):
                        result.append(Register(name=name, value=value['value']))
        else:
            in_frames = False
            for line in self._data.split('\n'):
                if in_frames:
                    splitted = line.split()

                    if len(splitted) == 0:
                        break

                    for i in range(0, len(splitted), 2):
                        register_name = splitted[i]
                        if not register_name.endswith(':'):
                            break

                        register_name = register_name[:-1]
                        register_value = int(splitted[i + 1], 16)

                        result.append(Register(name=register_name, value=register_value))

                if line.startswith(f'Thread {self.faulting_thread} crashed with ARM Thread State'):
                    in_frames = True

        return result

    @cached_property
    def exception_type(self):
        if self._is_json:
            return self._data['exception'].get('type')
        else:
            return self._parse_field('Exception Type')

    @cached_property
    def exception_subtype(self) -> Optional[str]:
        if self._is_json:
            return self._data['exception'].get('subtype')
        else:
            return self._parse_field('Exception Subtype')

    @cached_property
    def application_specific_information(self) -> Optional[str]:
        result = ''
        if self._is_json:
            asi = self._data.get('asi')
            if asi is None:
                return None
            return asi
        else:
            in_frames = False
            for line in self._data.split('\n'):
                if in_frames:
                    line = line.strip()
                    if len(line) == 0:
                        break

                    result += line + '\n'

                if line.startswith('Application Specific Information:'):
                    in_frames = True

        result = result.strip()
        if not result:
            return None
        return result

    def __str__(self) -> str:
        result = super().__str__()
        result += bold(f'Exception: {self.exception_type}\n')

        if self.exception_subtype:
            result += bold('Exception Subtype: ')
            result += f'{self.exception_subtype}\n'

        if self.application_specific_information:
            result += bold('Application Specific Information: ')
            result += str(self.application_specific_information)

        result += '\n'

        result += bold('Registers:')
        for i, register in enumerate(self.registers):
            if i % 4 == 0:
                result += '\n'

            result += f'{register.name} = 0x{register.value:016x} '.rjust(30)

        result += '\n\n'

        result += bold('Frames:\n')
        for frame in self.frames:
            image_base = '_HEADER'
            if frame.image_base is not None:
                image_base = f'0x{frame.image_base:x}'
            result += f'\t[{frame.image_name}] {image_base}'
            if frame.image_offset:
                result += f' + 0x{frame.image_offset:x}'
            if frame.symbol is not None:
                result += f' ({frame.symbol} + 0x{frame.symbol_offset:x})'
            result += '\n'

        return result


def get_crash_report_from_file(crash_report_file: IO) -> CrashReportBase:
    metadata = json.loads(crash_report_file.readline())

    try:
        bug_type = BugType(metadata['bug_type'])
    except ValueError:
        return CrashReportBase(metadata, crash_report_file.read(), crash_report_file.name)

    bug_type_parsers = {
        BugType.Crash_109: UserModeCrashReport,
        BugType.Crash_309: UserModeCrashReport,
        BugType.ExcResourceThreads_327: UserModeCrashReport,
        BugType.ExcResource_385: UserModeCrashReport,
    }

    parser = bug_type_parsers.get(bug_type)
    if parser is None:
        return CrashReportBase(metadata, crash_report_file.read(), crash_report_file.name)

    return parser(metadata, crash_report_file.read(), crash_report_file.name)


if __name__ == '__main__':
    with open(sys.argv[-1]) as f:
        print(get_crash_report_from_file(f))
