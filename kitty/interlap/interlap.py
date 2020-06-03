

#-----------------------------------------------------------------------------------------------------------
# from _testing import C
# from _testing import debug
# from _testing import urge
# from _testing import help
# from typing import NamedTuple
from typing import Union
from typing import Tuple
from typing import Iterable
from typing import List
from typing import Any
# from typing import NoReturn
# from typing import NewType
# from math import inf
from functools import total_ordering

#-----------------------------------------------------------------------------------------------------------
class InterlapError( Exception ): pass
class InterlapKeyError( KeyError, InterlapError ): pass
class InterlapValueError( ValueError, InterlapError ): pass


#-----------------------------------------------------------------------------------------------------------
def isa( T: Any, x: Any ) -> Any:
  ### thx to https://stackoverflow.com/a/49471187/7568091 ###
  ### TAINT This is much more complicated than it should be ###
  if getattr( T, '__origin__', None ) == Union: return isinstance( x, T.__args__ )
  return isinstance( x, T )

#-----------------------------------------------------------------------------------------------------------
### TAINT https://mypy.readthedocs.io/en/latest/cheat_sheet_py3.html#miscellaneous forward reference ###
# intinf          = Union[ int, inf, ]
# intinf          = Union[ int, str ]
# Lap             = Tuple[ Segment ]
# opt_gen_segment = Union[ gen_segment, None, ]
bi_int          = Tuple[ int, int ]
gen_segment     = Union[ 'Segment', bi_int, ]


#-----------------------------------------------------------------------------------------------------------
class Immutable:
  def __setattr__( me, *P: Any ) -> None:
    raise InterlapKeyError( "^E333^ forbidden to set attribute on immutable" )

#-----------------------------------------------------------------------------------------------------------
@total_ordering
class Segment( Immutable ):
  # __slots__ = [ 'lo', 'hi', ]

  #---------------------------------------------------------------------------------------------------------
  def __init__( me, lo: int, hi: int ) -> None:
    me.lo: int
    me.hi: int
    me.__dict__[ 'lo' ] = lo
    me.__dict__[ 'hi' ] = hi

  #---------------------------------------------------------------------------------------------------------
  def __iter__( me ) -> Iterable: yield me
  def __repr__( me ) -> str: return f"{me.__class__.__name__}( {me.lo}, {me.hi} )"
  def __hash__( me ) -> int: return hash( ( me.lo, me.hi, ) )

  #---------------------------------------------------------------------------------------------------------
  def __lt__( me, other: Any ) -> bool:
    if not isinstance( other, Segment ):
      raise InterlapValueError( f"^E336^ unable to compare a Segment with a {type( other )}" )
    return ( me.lo < other.lo ) or ( me.hi < other.hi ) # type: ignore

  #---------------------------------------------------------------------------------------------------------
  def __eq__( me, other: Any ) -> bool:
    if not isinstance( other, Segment ): return False
    return ( me.lo == other.lo ) and ( me.hi == other.hi )

  #---------------------------------------------------------------------------------------------------------
  @property
  def size( me ) -> int: return me.hi - me.lo + 1


#-----------------------------------------------------------------------------------------------------------
@total_ordering
class Lap( Immutable ):

  #---------------------------------------------------------------------------------------------------------
  def __init__( me, segments: Iterable[ Segment, ] = () ):
    me.segments: Tuple[ Segment, ]
    me.__dict__[ 'segments' ] = tuple( segments )

  #---------------------------------------------------------------------------------------------------------
  def __repr__(     me            ) -> str:       return f"Lap( {repr( me.segments )} )"
  def __iter__(     me            ) -> Iterable:  return iter( me.segments )
  def __len__(      me            ) -> int:       return len( me.segments )
  def __getitem__(  me, idx: int  ) -> Segment:   return me.segments[ idx ]

  #---------------------------------------------------------------------------------------------------------
  def __lt__( me, other: Any ) -> bool:
    if not isinstance( other, Lap ):
      raise InterlapValueError( f"^E339^ unable to compare a Lap with a {type( other )}" )
    if me.segments == other.segments: return False
    length = min( len( me ), len( other ) )
    if length == 0:
      if len( me ) == 0: return True
      return False
    for idx in range( 0, length ): # type: ignore
      if me.segments[ idx ] < other.segments[ idx ]: return True # type: ignore
    return False

  #---------------------------------------------------------------------------------------------------------
  def __eq__( me, other: Any ) -> bool:
    if not isinstance( other, Lap ): return False
    return me.segments == other.segments

  #---------------------------------------------------------------------------------------------------------
  @property
  def size( me ) -> int: return sum( ( s.size for s in me.segments ), 0 )

#-----------------------------------------------------------------------------------------------------------
def new_segment( lohi: gen_segment = None, *, lo: int = None, hi: int = None ) -> Segment:
  if isinstance( lohi, Segment ): return lohi
  if lohi is None:
    if not isinstance( lo, int ): raise InterlapValueError( f"^E342^ illegal arguments: lohi: {lohi}, lo: {lo}, hi: {hi}" )
    if not isinstance( hi, int ): raise InterlapValueError( f"^E345^ illegal arguments: lohi: {lohi}, lo: {lo}, hi: {hi}" )
  else:
    if lo != None: raise InterlapValueError( f"^E342^ illegal arguments: lohi: {lohi}, lo: {lo}, hi: {hi}" )
    if hi != None: raise InterlapValueError( f"^E345^ illegal arguments: lohi: {lohi}, lo: {lo}, hi: {hi}" )
    if len( lohi ) != 2:
      raise InterlapValueError( f"^E348^ expected a tuple of length 2, got one with length {len( lohi )}: lohi: {lohi}")
    lo, hi = lohi
  #.........................................................................................................
  # if not isinstance( lo, int ): raise InterlapValueError( f"^E300^ expected an integer, got a {type( lo )}" ) # unreachable?
  # if not isinstance( hi, int ): raise InterlapValueError( f"^E300^ expected an integer, got a {type( hi )}" ) # unreachable?
  if not lo <= hi: raise InterlapValueError( f"^E351^ expected lo <= hi, got {lo} and {hi}" )
  #.........................................................................................................
  return Segment( lo, hi, )

#-----------------------------------------------------------------------------------------------------------
def new_lap( *P: gen_segment ) -> Lap: return merge_segments( *P ) # type: ignore


#===========================================================================================================
#
#-----------------------------------------------------------------------------------------------------------
# class A:
# @classmethod ... def segments_are_disjunct( cls, ... )
def segments_are_disjunct( me: gen_segment, other: gen_segment ) -> bool:
  """Two segments are disjunct iff they have no point in common."""
  return _segments_are_disjunct( new_segment( me ), new_segment( other ) )

#-----------------------------------------------------------------------------------------------------------
def segments_overlap( me: gen_segment, other: gen_segment ) -> bool:
  """Two segments overlap iff they have at least one point in common."""
  return _segments_overlap( new_segment( me ), new_segment( other ) )

#-----------------------------------------------------------------------------------------------------------
def segments_are_adjacent( me: gen_segment, other: gen_segment ) -> bool:
  """Two segments are adjacent if the upper bound of the one directly precedes the lower bound of the
  other."""
  return _segments_are_adjacent( new_segment( me ), new_segment( other ) )

#-----------------------------------------------------------------------------------------------------------
def merge_segments( *P: gen_segment ) -> Lap:
  if len( P ) == 0: return Lap()
  if len( P ) == 1: return Lap( ( new_segment( P[ 0 ] ), ) )
  if len( P ) == 2: return Lap( _merge_two_segments( new_segment( P[ 0 ] ), new_segment( P[ 1 ] ) ) )
  return Lap( _merge_segments( *P ) )

#-----------------------------------------------------------------------------------------------------------
def subtract_segments( *P: gen_segment ) -> Lap:
  if len( P ) == 0: return Lap()
  if len( P ) == 1: return Lap( ( new_segment( P[ 0 ] ), ) )
  if len( P ) == 2: return Lap( _subtract_two_segments( new_segment( P[ 0 ] ), new_segment( P[ 1 ] ) ) )
  me, *others               = P
  me                        = new_segment( me )
  others: List[ Segment, ]  = _merge_segments( *others )
  # urge( '^334^', f"others {others}" )
  R: List[ Segment, ]       = []
  idx                       = -1
  last_idx                  = len( others ) - 1
  leftovers:  List[ Segment, ]
  other:      Segment
  while True:
    idx      += +1
    if idx > last_idx: break
    other     = others[ idx ]
    leftovers = _subtract_two_segments( me, other )
    if len( leftovers ) == 0:
      continue
    if len( leftovers ) == 1:
      me = leftovers[ 0 ]
    else:
      R  += leftovers[ 0 : len( leftovers ) - 1 ] ### TAINT use negative index ###
      me  = leftovers[ -1 ]
    # help( "^443^", idx, f"me {me}", f"other {other}", f"leftovers {leftovers}", f"R {R}" )
  R.append( me )
  R.sort()
  return Lap( R )

#-----------------------------------------------------------------------------------------------------------
def _subtract_two_segments( a: Segment, b: Segment ) -> List[ Segment, ]:
  if segments_are_disjunct( a, b ):  return [ a, ]
  if a == b:            return []
  if b.lo <= a.lo:
    if b.hi >= a.hi: return []
    return [ Segment( b.hi + 1, a.hi ), ]
  if b.hi >= a.hi:
    return [ Segment( a.lo, b.lo - 1 ), ]
  return [ Segment( a.lo, b.lo - 1 ), Segment( b.hi + 1, a.hi ), ]


#===========================================================================================================
#
#-----------------------------------------------------------------------------------------------------------
def _segments_are_disjunct( me: Segment, other: Segment ) -> bool:
  return ( me.hi < other.lo ) or ( other.hi < me.lo )

#-----------------------------------------------------------------------------------------------------------
def _segments_overlap( me: Segment, other: Segment ) -> bool:
  return not ( ( me.hi < other.lo ) or ( other.hi < me.lo ) )

#-----------------------------------------------------------------------------------------------------------
def _segments_are_adjacent( me: Segment, other: Segment ) -> bool:
  return ( me.hi + 1 == other.lo ) or ( other.hi + 1 == me.lo )

#-----------------------------------------------------------------------------------------------------------
def _merge_segments( *P: gen_segment ) -> List[ Segment ]:
  if len( P ) == 0: return []
  if len( P ) == 1: return [ new_segment( P[ 0 ] ), ]
  if len( P ) == 2: return _merge_two_segments( new_segment( P[ 0 ] ), new_segment( P[ 1 ] ) )
  segments      = [ new_segment( s ) for s in P ]
  segments.sort()
  reference, \
  segments      = segments[ 0 ], segments[ 1 : ]
  R             = []
  idx           = -1
  last_idx      = len( segments ) - 1
  while True:
    idx += +1
    if idx > last_idx: break
    segment = segments[ idx ]
    if segment == reference: continue
    merged_segments = _merge_two_segments( reference, segment )
    if len( merged_segments ) > 1:
      R.append( merged_segments[ 0 ] )
      reference = merged_segments[ 1 ]
      continue
    reference = merged_segments[ 0 ]
  R.append( reference )
  return R

#-----------------------------------------------------------------------------------------------------------
def _merge_two_segments( a: Segment, b: Segment ) -> List[ Segment ]:
  if a.lo > b.lo: a, b = b, a
  if b.lo > a.hi + 1: return [ a, b, ]
  return [ new_segment( ( a.lo, max( a.hi, b.hi ), ) ), ]


############################################################################################################
if __name__ == '__main__':
  pass
  # test()
