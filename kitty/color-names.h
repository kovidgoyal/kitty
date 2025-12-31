/* ANSI-C code produced by gperf version 3.3 */
/* Command-line: gperf -m 2000 --struct-type --includes --readonly-tables --lookup-function-name in_color_name_set --global-table --null-strings --hash-function-name color_name_hash --word-array-name color_names --pic --compare-strncmp /dev/stdin  */
/* Computed positions: -k'1,3,5-9,12-15,$' */

#if !((' ' == 32) && ('!' == 33) && ('"' == 34) && ('#' == 35) \
      && ('%' == 37) && ('&' == 38) && ('\'' == 39) && ('(' == 40) \
      && (')' == 41) && ('*' == 42) && ('+' == 43) && (',' == 44) \
      && ('-' == 45) && ('.' == 46) && ('/' == 47) && ('0' == 48) \
      && ('1' == 49) && ('2' == 50) && ('3' == 51) && ('4' == 52) \
      && ('5' == 53) && ('6' == 54) && ('7' == 55) && ('8' == 56) \
      && ('9' == 57) && (':' == 58) && (';' == 59) && ('<' == 60) \
      && ('=' == 61) && ('>' == 62) && ('?' == 63) && ('A' == 65) \
      && ('B' == 66) && ('C' == 67) && ('D' == 68) && ('E' == 69) \
      && ('F' == 70) && ('G' == 71) && ('H' == 72) && ('I' == 73) \
      && ('J' == 74) && ('K' == 75) && ('L' == 76) && ('M' == 77) \
      && ('N' == 78) && ('O' == 79) && ('P' == 80) && ('Q' == 81) \
      && ('R' == 82) && ('S' == 83) && ('T' == 84) && ('U' == 85) \
      && ('V' == 86) && ('W' == 87) && ('X' == 88) && ('Y' == 89) \
      && ('Z' == 90) && ('[' == 91) && ('\\' == 92) && (']' == 93) \
      && ('^' == 94) && ('_' == 95) && ('a' == 97) && ('b' == 98) \
      && ('c' == 99) && ('d' == 100) && ('e' == 101) && ('f' == 102) \
      && ('g' == 103) && ('h' == 104) && ('i' == 105) && ('j' == 106) \
      && ('k' == 107) && ('l' == 108) && ('m' == 109) && ('n' == 110) \
      && ('o' == 111) && ('p' == 112) && ('q' == 113) && ('r' == 114) \
      && ('s' == 115) && ('t' == 116) && ('u' == 117) && ('v' == 118) \
      && ('w' == 119) && ('x' == 120) && ('y' == 121) && ('z' == 122) \
      && ('{' == 123) && ('|' == 124) && ('}' == 125) && ('~' == 126))
/* The character set is not based on ISO-646.  */
#error "gperf generated tables don't work with this execution character set. Please report a bug to <bug-gperf@gnu.org>."
#endif

#line 1 "/dev/stdin"
struct Keyword { int name, value; };
#include <string.h>

#define TOTAL_KEYWORDS 753
#define MIN_WORD_LENGTH 3
#define MAX_WORD_LENGTH 22
#define MIN_HASH_VALUE 172
#define MAX_HASH_VALUE 3478
/* maximum key range = 3307, duplicates = 0 */

#ifdef __GNUC__
__inline
#else
#ifdef __cplusplus
inline
#endif
#endif
static unsigned int
color_name_hash (register const char *str, register size_t len)
{
  static const unsigned short asso_values[] =
    {
      3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479,
      3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479,
      3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479,
      3479, 3479,  384, 3479, 3479, 3479, 3479, 3479, 3479, 3479,
      3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479,  689,   61,
        60,   57,   56,  917,  884,  827,  824,  815, 3479, 3479,
      3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479,
      3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479,
      3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479,
      3479, 3479, 3479, 3479, 3479, 3479, 3479,   72,   68,  615,
        56,   56,   92,   56,  375,  575,   56,  631,   86,  289,
       101,   75,  202,  134,   57,   56,  191,  137,  987,  777,
      3479,  239, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479,
      3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479,
      3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479,
      3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479,
      3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479,
      3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479,
      3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479,
      3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479,
      3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479,
      3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479,
      3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479,
      3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479,
      3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479, 3479,
      3479, 3479, 3479, 3479, 3479, 3479
    };
  register unsigned int hval = len;

  switch (hval)
    {
      default:
        hval += asso_values[(unsigned char)str[14]];
#if (defined __cplusplus && (__cplusplus >= 201703L || (__cplusplus >= 201103L && defined __clang__ && __clang_major__ + (__clang_minor__ >= 9) > 3))) || (defined __STDC_VERSION__ && __STDC_VERSION__ >= 202000L && ((defined __GNUC__ && __GNUC__ >= 10) || (defined __clang__ && __clang_major__ >= 9)))
      [[fallthrough]];
#elif (defined __GNUC__ && __GNUC__ >= 7) || (defined __clang__ && __clang_major__ >= 10)
      __attribute__ ((__fallthrough__));
#endif
      /*FALLTHROUGH*/
      case 14:
        hval += asso_values[(unsigned char)str[13]];
#if (defined __cplusplus && (__cplusplus >= 201703L || (__cplusplus >= 201103L && defined __clang__ && __clang_major__ + (__clang_minor__ >= 9) > 3))) || (defined __STDC_VERSION__ && __STDC_VERSION__ >= 202000L && ((defined __GNUC__ && __GNUC__ >= 10) || (defined __clang__ && __clang_major__ >= 9)))
      [[fallthrough]];
#elif (defined __GNUC__ && __GNUC__ >= 7) || (defined __clang__ && __clang_major__ >= 10)
      __attribute__ ((__fallthrough__));
#endif
      /*FALLTHROUGH*/
      case 13:
        hval += asso_values[(unsigned char)str[12]];
#if (defined __cplusplus && (__cplusplus >= 201703L || (__cplusplus >= 201103L && defined __clang__ && __clang_major__ + (__clang_minor__ >= 9) > 3))) || (defined __STDC_VERSION__ && __STDC_VERSION__ >= 202000L && ((defined __GNUC__ && __GNUC__ >= 10) || (defined __clang__ && __clang_major__ >= 9)))
      [[fallthrough]];
#elif (defined __GNUC__ && __GNUC__ >= 7) || (defined __clang__ && __clang_major__ >= 10)
      __attribute__ ((__fallthrough__));
#endif
      /*FALLTHROUGH*/
      case 12:
        hval += asso_values[(unsigned char)str[11]];
#if (defined __cplusplus && (__cplusplus >= 201703L || (__cplusplus >= 201103L && defined __clang__ && __clang_major__ + (__clang_minor__ >= 9) > 3))) || (defined __STDC_VERSION__ && __STDC_VERSION__ >= 202000L && ((defined __GNUC__ && __GNUC__ >= 10) || (defined __clang__ && __clang_major__ >= 9)))
      [[fallthrough]];
#elif (defined __GNUC__ && __GNUC__ >= 7) || (defined __clang__ && __clang_major__ >= 10)
      __attribute__ ((__fallthrough__));
#endif
      /*FALLTHROUGH*/
      case 11:
      case 10:
      case 9:
        hval += asso_values[(unsigned char)str[8]];
#if (defined __cplusplus && (__cplusplus >= 201703L || (__cplusplus >= 201103L && defined __clang__ && __clang_major__ + (__clang_minor__ >= 9) > 3))) || (defined __STDC_VERSION__ && __STDC_VERSION__ >= 202000L && ((defined __GNUC__ && __GNUC__ >= 10) || (defined __clang__ && __clang_major__ >= 9)))
      [[fallthrough]];
#elif (defined __GNUC__ && __GNUC__ >= 7) || (defined __clang__ && __clang_major__ >= 10)
      __attribute__ ((__fallthrough__));
#endif
      /*FALLTHROUGH*/
      case 8:
        hval += asso_values[(unsigned char)str[7]];
#if (defined __cplusplus && (__cplusplus >= 201703L || (__cplusplus >= 201103L && defined __clang__ && __clang_major__ + (__clang_minor__ >= 9) > 3))) || (defined __STDC_VERSION__ && __STDC_VERSION__ >= 202000L && ((defined __GNUC__ && __GNUC__ >= 10) || (defined __clang__ && __clang_major__ >= 9)))
      [[fallthrough]];
#elif (defined __GNUC__ && __GNUC__ >= 7) || (defined __clang__ && __clang_major__ >= 10)
      __attribute__ ((__fallthrough__));
#endif
      /*FALLTHROUGH*/
      case 7:
        hval += asso_values[(unsigned char)str[6]];
#if (defined __cplusplus && (__cplusplus >= 201703L || (__cplusplus >= 201103L && defined __clang__ && __clang_major__ + (__clang_minor__ >= 9) > 3))) || (defined __STDC_VERSION__ && __STDC_VERSION__ >= 202000L && ((defined __GNUC__ && __GNUC__ >= 10) || (defined __clang__ && __clang_major__ >= 9)))
      [[fallthrough]];
#elif (defined __GNUC__ && __GNUC__ >= 7) || (defined __clang__ && __clang_major__ >= 10)
      __attribute__ ((__fallthrough__));
#endif
      /*FALLTHROUGH*/
      case 6:
        hval += asso_values[(unsigned char)str[5]];
#if (defined __cplusplus && (__cplusplus >= 201703L || (__cplusplus >= 201103L && defined __clang__ && __clang_major__ + (__clang_minor__ >= 9) > 3))) || (defined __STDC_VERSION__ && __STDC_VERSION__ >= 202000L && ((defined __GNUC__ && __GNUC__ >= 10) || (defined __clang__ && __clang_major__ >= 9)))
      [[fallthrough]];
#elif (defined __GNUC__ && __GNUC__ >= 7) || (defined __clang__ && __clang_major__ >= 10)
      __attribute__ ((__fallthrough__));
#endif
      /*FALLTHROUGH*/
      case 5:
        hval += asso_values[(unsigned char)str[4]];
#if (defined __cplusplus && (__cplusplus >= 201703L || (__cplusplus >= 201103L && defined __clang__ && __clang_major__ + (__clang_minor__ >= 9) > 3))) || (defined __STDC_VERSION__ && __STDC_VERSION__ >= 202000L && ((defined __GNUC__ && __GNUC__ >= 10) || (defined __clang__ && __clang_major__ >= 9)))
      [[fallthrough]];
#elif (defined __GNUC__ && __GNUC__ >= 7) || (defined __clang__ && __clang_major__ >= 10)
      __attribute__ ((__fallthrough__));
#endif
      /*FALLTHROUGH*/
      case 4:
      case 3:
        hval += asso_values[(unsigned char)str[2]];
#if (defined __cplusplus && (__cplusplus >= 201703L || (__cplusplus >= 201103L && defined __clang__ && __clang_major__ + (__clang_minor__ >= 9) > 3))) || (defined __STDC_VERSION__ && __STDC_VERSION__ >= 202000L && ((defined __GNUC__ && __GNUC__ >= 10) || (defined __clang__ && __clang_major__ >= 9)))
      [[fallthrough]];
#elif (defined __GNUC__ && __GNUC__ >= 7) || (defined __clang__ && __clang_major__ >= 10)
      __attribute__ ((__fallthrough__));
#endif
      /*FALLTHROUGH*/
      case 2:
      case 1:
        hval += asso_values[(unsigned char)str[0]];
        break;
    }
  return hval + asso_values[(unsigned char)str[len - 1]];
}

struct stringpool_t
  {
    char stringpool_str172[sizeof("red")];
    char stringpool_str173[sizeof("red4")];
    char stringpool_str174[sizeof("red3")];
    char stringpool_str177[sizeof("red2")];
    char stringpool_str178[sizeof("red1")];
    char stringpool_str202[sizeof("gold")];
    char stringpool_str229[sizeof("grey4")];
    char stringpool_str231[sizeof("grey3")];
    char stringpool_str237[sizeof("grey2")];
    char stringpool_str239[sizeof("grey1")];
    char stringpool_str245[sizeof("gray4")];
    char stringpool_str247[sizeof("gray3")];
    char stringpool_str248[sizeof("snow4")];
    char stringpool_str250[sizeof("snow3")];
    char stringpool_str253[sizeof("gray2")];
    char stringpool_str255[sizeof("gray1")];
    char stringpool_str256[sizeof("snow2")];
    char stringpool_str258[sizeof("snow1")];
    char stringpool_str259[sizeof("gold4")];
    char stringpool_str261[sizeof("gold3")];
    char stringpool_str265[sizeof("blue")];
    char stringpool_str267[sizeof("gold2")];
    char stringpool_str269[sizeof("gold1")];
    char stringpool_str286[sizeof("grey44")];
    char stringpool_str287[sizeof("grey34")];
    char stringpool_str288[sizeof("grey43")];
    char stringpool_str289[sizeof("grey33")];
    char stringpool_str290[sizeof("grey24")];
    char stringpool_str291[sizeof("grey14")];
    char stringpool_str292[sizeof("grey23")];
    char stringpool_str293[sizeof("grey13")];
    char stringpool_str294[sizeof("grey42")];
    char stringpool_str295[sizeof("grey32")];
    char stringpool_str296[sizeof("grey41")];
    char stringpool_str297[sizeof("grey31")];
    char stringpool_str298[sizeof("grey22")];
    char stringpool_str299[sizeof("grey12")];
    char stringpool_str300[sizeof("grey21")];
    char stringpool_str301[sizeof("grey11")];
    char stringpool_str302[sizeof("gray44")];
    char stringpool_str303[sizeof("gray34")];
    char stringpool_str304[sizeof("gray43")];
    char stringpool_str305[sizeof("gray33")];
    char stringpool_str306[sizeof("gray24")];
    char stringpool_str307[sizeof("gray14")];
    char stringpool_str308[sizeof("gray23")];
    char stringpool_str309[sizeof("gray13")];
    char stringpool_str310[sizeof("gray42")];
    char stringpool_str311[sizeof("gray32")];
    char stringpool_str312[sizeof("gray41")];
    char stringpool_str313[sizeof("gray31")];
    char stringpool_str314[sizeof("gray22")];
    char stringpool_str315[sizeof("gray12")];
    char stringpool_str316[sizeof("gray21")];
    char stringpool_str317[sizeof("gray11")];
    char stringpool_str319[sizeof("green")];
    char stringpool_str321[sizeof("orange")];
    char stringpool_str322[sizeof("blue4")];
    char stringpool_str324[sizeof("blue3")];
    char stringpool_str326[sizeof("azure")];
    char stringpool_str330[sizeof("blue2")];
    char stringpool_str331[sizeof("green4")];
    char stringpool_str332[sizeof("blue1")];
    char stringpool_str333[sizeof("green3")];
    char stringpool_str339[sizeof("green2")];
    char stringpool_str341[sizeof("green1")];
    char stringpool_str345[sizeof("darkred")];
    char stringpool_str350[sizeof("brown")];
    char stringpool_str352[sizeof("tan4")];
    char stringpool_str353[sizeof("tan3")];
    char stringpool_str355[sizeof("grey")];
    char stringpool_str356[sizeof("tan2")];
    char stringpool_str357[sizeof("tan1")];
    char stringpool_str362[sizeof("brown4")];
    char stringpool_str363[sizeof("sienna")];
    char stringpool_str364[sizeof("brown3")];
    char stringpool_str370[sizeof("brown2")];
    char stringpool_str371[sizeof("gray")];
    char stringpool_str372[sizeof("brown1")];
    char stringpool_str378[sizeof("orange4")];
    char stringpool_str379[sizeof("bisque")];
    char stringpool_str380[sizeof("orange3")];
    char stringpool_str383[sizeof("azure4")];
    char stringpool_str385[sizeof("azure3")];
    char stringpool_str386[sizeof("orange2")];
    char stringpool_str388[sizeof("orange1")];
    char stringpool_str391[sizeof("azure2")];
    char stringpool_str393[sizeof("azure1")];
    char stringpool_str394[sizeof("linen")];
    char stringpool_str396[sizeof("tan")];
    char stringpool_str400[sizeof("peru")];
    char stringpool_str404[sizeof("sienna4")];
    char stringpool_str406[sizeof("sienna3")];
    char stringpool_str412[sizeof("sienna2")];
    char stringpool_str414[sizeof("sienna1")];
    char stringpool_str420[sizeof("pink4")];
    char stringpool_str422[sizeof("pink3")];
    char stringpool_str425[sizeof("salmon")];
    char stringpool_str428[sizeof("pink2")];
    char stringpool_str430[sizeof("pink1")];
    char stringpool_str436[sizeof("bisque4")];
    char stringpool_str437[sizeof("salmon4")];
    char stringpool_str438[sizeof("bisque3")];
    char stringpool_str439[sizeof("salmon3")];
    char stringpool_str444[sizeof("bisque2")];
    char stringpool_str445[sizeof("salmon2")];
    char stringpool_str446[sizeof("bisque1")];
    char stringpool_str447[sizeof("salmon1")];
    char stringpool_str456[sizeof("plum4")];
    char stringpool_str458[sizeof("plum3")];
    char stringpool_str463[sizeof("purple")];
    char stringpool_str464[sizeof("plum2")];
    char stringpool_str466[sizeof("plum1")];
    char stringpool_str493[sizeof("orangered")];
    char stringpool_str494[sizeof("orangered4")];
    char stringpool_str495[sizeof("orangered3")];
    char stringpool_str498[sizeof("orangered2")];
    char stringpool_str499[sizeof("orangered1")];
    char stringpool_str507[sizeof("seagreen")];
    char stringpool_str519[sizeof("seagreen4")];
    char stringpool_str520[sizeof("purple4")];
    char stringpool_str521[sizeof("seagreen3")];
    char stringpool_str522[sizeof("purple3")];
    char stringpool_str524[sizeof("darkblue")];
    char stringpool_str527[sizeof("seagreen2")];
    char stringpool_str528[sizeof("purple2")];
    char stringpool_str529[sizeof("seagreen1")];
    char stringpool_str530[sizeof("purple1")];
    char stringpool_str531[sizeof("debianred")];
    char stringpool_str540[sizeof("darkorange")];
    char stringpool_str541[sizeof("darkorange4")];
    char stringpool_str542[sizeof("darkorange3")];
    char stringpool_str545[sizeof("darkorange2")];
    char stringpool_str546[sizeof("darkorange1")];
    char stringpool_str549[sizeof("darkgreen")];
    char stringpool_str551[sizeof("springgreen")];
    char stringpool_str552[sizeof("goldenrod")];
    char stringpool_str553[sizeof("goldenrod4")];
    char stringpool_str554[sizeof("goldenrod3")];
    char stringpool_str557[sizeof("goldenrod2")];
    char stringpool_str558[sizeof("goldenrod1")];
    char stringpool_str563[sizeof("springgreen4")];
    char stringpool_str564[sizeof("sea green")];
    char stringpool_str565[sizeof("springgreen3")];
    char stringpool_str566[sizeof("saddlebrown")];
    char stringpool_str571[sizeof("springgreen2")];
    char stringpool_str573[sizeof("springgreen1")];
    char stringpool_str582[sizeof("dodgerblue")];
    char stringpool_str583[sizeof("dodgerblue4")];
    char stringpool_str584[sizeof("dodgerblue3")];
    char stringpool_str587[sizeof("dodgerblue2")];
    char stringpool_str588[sizeof("dodgerblue1")];
    char stringpool_str596[sizeof("slateblue")];
    char stringpool_str597[sizeof("slateblue4")];
    char stringpool_str598[sizeof("slateblue3")];
    char stringpool_str601[sizeof("slateblue2")];
    char stringpool_str602[sizeof("slateblue1")];
    char stringpool_str610[sizeof("steelblue")];
    char stringpool_str611[sizeof("steelblue4")];
    char stringpool_str612[sizeof("steelblue3")];
    char stringpool_str615[sizeof("steelblue2")];
    char stringpool_str616[sizeof("steelblue1")];
    char stringpool_str624[sizeof("darkseagreen")];
    char stringpool_str629[sizeof("maroon")];
    char stringpool_str632[sizeof("plum")];
    char stringpool_str636[sizeof("darkseagreen4")];
    char stringpool_str637[sizeof("skyblue")];
    char stringpool_str638[sizeof("darkseagreen3")];
    char stringpool_str641[sizeof("maroon4")];
    char stringpool_str642[sizeof("darkgoldenrod")];
    char stringpool_str643[sizeof("maroon3")];
    char stringpool_str644[sizeof("darkseagreen2")];
    char stringpool_str646[sizeof("darkseagreen1")];
    char stringpool_str649[sizeof("maroon2")];
    char stringpool_str651[sizeof("maroon1")];
    char stringpool_str669[sizeof("lightgreen")];
    char stringpool_str674[sizeof("slategray4")];
    char stringpool_str675[sizeof("slategray3")];
    char stringpool_str677[sizeof("forestgreen")];
    char stringpool_str678[sizeof("slategray2")];
    char stringpool_str679[sizeof("slategray1")];
    char stringpool_str680[sizeof("palegreen4")];
    char stringpool_str681[sizeof("palegreen3")];
    char stringpool_str684[sizeof("palegreen2")];
    char stringpool_str685[sizeof("palegreen1")];
    char stringpool_str694[sizeof("skyblue4")];
    char stringpool_str696[sizeof("skyblue3")];
    char stringpool_str699[sizeof("darkgoldenrod4")];
    char stringpool_str701[sizeof("darkgoldenrod3")];
    char stringpool_str702[sizeof("skyblue2")];
    char stringpool_str704[sizeof("skyblue1")];
    char stringpool_str706[sizeof("sky blue")];
    char stringpool_str707[sizeof("darkgoldenrod2")];
    char stringpool_str709[sizeof("darkgoldenrod1")];
    char stringpool_str724[sizeof("palegreen")];
    char stringpool_str730[sizeof("dark red")];
    char stringpool_str745[sizeof("lightblue")];
    char stringpool_str746[sizeof("lightblue4")];
    char stringpool_str747[sizeof("lightblue3")];
    char stringpool_str750[sizeof("lightblue2")];
    char stringpool_str751[sizeof("lightblue1")];
    char stringpool_str760[sizeof("beige")];
    char stringpool_str768[sizeof("darkgrey")];
    char stringpool_str770[sizeof("darkmagenta")];
    char stringpool_str784[sizeof("darkgray")];
    char stringpool_str788[sizeof("magenta")];
    char stringpool_str792[sizeof("cyan")];
    char stringpool_str794[sizeof("royalblue")];
    char stringpool_str795[sizeof("royalblue4")];
    char stringpool_str796[sizeof("royalblue3")];
    char stringpool_str799[sizeof("royalblue2")];
    char stringpool_str800[sizeof("royalblue1")];
    char stringpool_str802[sizeof("darksalmon")];
    char stringpool_str804[sizeof("cyan4")];
    char stringpool_str806[sizeof("cyan3")];
    char stringpool_str811[sizeof("limegreen")];
    char stringpool_str812[sizeof("cyan2")];
    char stringpool_str814[sizeof("cyan1")];
    char stringpool_str817[sizeof("palegoldenrod")];
    char stringpool_str822[sizeof("orange red")];
    char stringpool_str825[sizeof("seashell")];
    char stringpool_str827[sizeof("tomato")];
    char stringpool_str829[sizeof("magenta4")];
    char stringpool_str830[sizeof("dodger blue")];
    char stringpool_str831[sizeof("magenta3")];
    char stringpool_str833[sizeof("dark green")];
    char stringpool_str836[sizeof("darkslateblue")];
    char stringpool_str837[sizeof("magenta2")];
    char stringpool_str839[sizeof("magenta1")];
    char stringpool_str840[sizeof("slategrey")];
    char stringpool_str844[sizeof("lightseagreen")];
    char stringpool_str849[sizeof("coral")];
    char stringpool_str852[sizeof("seashell4")];
    char stringpool_str854[sizeof("seashell3")];
    char stringpool_str856[sizeof("slategray")];
    char stringpool_str860[sizeof("seashell2")];
    char stringpool_str862[sizeof("seashell1")];
    char stringpool_str864[sizeof("lightgoldenrod")];
    char stringpool_str865[sizeof("tomato4")];
    char stringpool_str867[sizeof("tomato3")];
    char stringpool_str869[sizeof("dark orange")];
    char stringpool_str873[sizeof("tomato2")];
    char stringpool_str875[sizeof("tomato1")];
    char stringpool_str876[sizeof("coral4")];
    char stringpool_str878[sizeof("coral3")];
    char stringpool_str884[sizeof("coral2")];
    char stringpool_str886[sizeof("coral1")];
    char stringpool_str893[sizeof("mistyrose")];
    char stringpool_str894[sizeof("mistyrose4")];
    char stringpool_str895[sizeof("mistyrose3")];
    char stringpool_str898[sizeof("mistyrose2")];
    char stringpool_str899[sizeof("mistyrose1")];
    char stringpool_str909[sizeof("dark blue")];
    char stringpool_str912[sizeof("snow")];
    char stringpool_str921[sizeof("lightgoldenrod4")];
    char stringpool_str923[sizeof("lightgoldenrod3")];
    char stringpool_str924[sizeof("lightyellow4")];
    char stringpool_str925[sizeof("slate blue")];
    char stringpool_str926[sizeof("lightyellow3")];
    char stringpool_str929[sizeof("lightgoldenrod2")];
    char stringpool_str931[sizeof("lightgoldenrod1")];
    char stringpool_str932[sizeof("lightyellow2")];
    char stringpool_str934[sizeof("lightyellow1")];
    char stringpool_str937[sizeof("oldlace")];
    char stringpool_str938[sizeof("pink")];
    char stringpool_str939[sizeof("steel blue")];
    char stringpool_str943[sizeof("dimgrey")];
    char stringpool_str948[sizeof("lightsalmon")];
    char stringpool_str950[sizeof("darkturquoise")];
    char stringpool_str959[sizeof("dimgray")];
    char stringpool_str960[sizeof("lightsalmon4")];
    char stringpool_str962[sizeof("lightsalmon3")];
    char stringpool_str968[sizeof("lightsalmon2")];
    char stringpool_str970[sizeof("lightsalmon1")];
    char stringpool_str977[sizeof("saddle brown")];
    char stringpool_str981[sizeof("spring green")];
    char stringpool_str986[sizeof("slate grey")];
    char stringpool_str989[sizeof("lightgrey")];
    char stringpool_str998[sizeof("light green")];
    char stringpool_str1000[sizeof("dim grey")];
    char stringpool_str1002[sizeof("slate gray")];
    char stringpool_str1005[sizeof("lightgray")];
    char stringpool_str1007[sizeof("ivory4")];
    char stringpool_str1008[sizeof("pale green")];
    char stringpool_str1009[sizeof("ivory3")];
    char stringpool_str1011[sizeof("darkslategray4")];
    char stringpool_str1013[sizeof("darkslategray3")];
    char stringpool_str1015[sizeof("ivory2")];
    char stringpool_str1016[sizeof("dim gray")];
    char stringpool_str1017[sizeof("ivory1")];
    char stringpool_str1019[sizeof("darkslategray2")];
    char stringpool_str1021[sizeof("darkslategray1")];
    char stringpool_str1024[sizeof("old lace")];
    char stringpool_str1025[sizeof("olivedrab4")];
    char stringpool_str1026[sizeof("olivedrab3")];
    char stringpool_str1028[sizeof("dark goldenrod")];
    char stringpool_str1029[sizeof("olivedrab2")];
    char stringpool_str1030[sizeof("olivedrab1")];
    char stringpool_str1036[sizeof("olivedrab")];
    char stringpool_str1038[sizeof("indianred")];
    char stringpool_str1039[sizeof("indianred4")];
    char stringpool_str1040[sizeof("indianred3")];
    char stringpool_str1041[sizeof("lightsteelblue")];
    char stringpool_str1043[sizeof("indianred2")];
    char stringpool_str1044[sizeof("indianred1")];
    char stringpool_str1045[sizeof("grey94")];
    char stringpool_str1046[sizeof("gainsboro")];
    char stringpool_str1047[sizeof("grey93")];
    char stringpool_str1053[sizeof("grey92")];
    char stringpool_str1054[sizeof("grey84")];
    char stringpool_str1055[sizeof("grey91")];
    char stringpool_str1056[sizeof("grey83")];
    char stringpool_str1057[sizeof("grey74")];
    char stringpool_str1059[sizeof("grey73")];
    char stringpool_str1061[sizeof("gray94")];
    char stringpool_str1062[sizeof("grey82")];
    char stringpool_str1063[sizeof("gray93")];
    char stringpool_str1064[sizeof("grey81")];
    char stringpool_str1065[sizeof("grey72")];
    char stringpool_str1067[sizeof("grey71")];
    char stringpool_str1069[sizeof("gray92")];
    char stringpool_str1070[sizeof("gray84")];
    char stringpool_str1071[sizeof("gray91")];
    char stringpool_str1072[sizeof("gray83")];
    char stringpool_str1073[sizeof("gray74")];
    char stringpool_str1074[sizeof("light blue")];
    char stringpool_str1075[sizeof("gray73")];
    char stringpool_str1078[sizeof("gray82")];
    char stringpool_str1080[sizeof("gray81")];
    char stringpool_str1081[sizeof("gray72")];
    char stringpool_str1083[sizeof("gray71")];
    char stringpool_str1087[sizeof("lightslateblue")];
    char stringpool_str1092[sizeof("sandy brown")];
    char stringpool_str1095[sizeof("lime green")];
    char stringpool_str1098[sizeof("lightsteelblue4")];
    char stringpool_str1100[sizeof("lightsteelblue3")];
    char stringpool_str1106[sizeof("lightsteelblue2")];
    char stringpool_str1107[sizeof("forest green")];
    char stringpool_str1108[sizeof("lightsteelblue1")];
    char stringpool_str1112[sizeof("dark salmon")];
    char stringpool_str1114[sizeof("grey64")];
    char stringpool_str1115[sizeof("aliceblue")];
    char stringpool_str1116[sizeof("grey63")];
    char stringpool_str1121[sizeof("darkslategrey")];
    char stringpool_str1122[sizeof("grey62")];
    char stringpool_str1123[sizeof("royal blue")];
    char stringpool_str1124[sizeof("grey61")];
    char stringpool_str1125[sizeof("paleturquoise")];
    char stringpool_str1126[sizeof("dark magenta")];
    char stringpool_str1128[sizeof("mediumblue")];
    char stringpool_str1130[sizeof("gray64")];
    char stringpool_str1132[sizeof("gray63")];
    char stringpool_str1133[sizeof("ivory")];
    char stringpool_str1135[sizeof("light grey")];
    char stringpool_str1137[sizeof("darkslategray")];
    char stringpool_str1138[sizeof("gray62")];
    char stringpool_str1140[sizeof("gray61")];
    char stringpool_str1142[sizeof("wheat4")];
    char stringpool_str1144[sizeof("wheat3")];
    char stringpool_str1145[sizeof("light salmon")];
    char stringpool_str1147[sizeof("grey54")];
    char stringpool_str1149[sizeof("grey53")];
    char stringpool_str1150[sizeof("wheat2")];
    char stringpool_str1151[sizeof("light gray")];
    char stringpool_str1152[sizeof("wheat1")];
    char stringpool_str1153[sizeof("dark grey")];
    char stringpool_str1155[sizeof("grey52")];
    char stringpool_str1157[sizeof("grey51")];
    char stringpool_str1162[sizeof("thistle")];
    char stringpool_str1163[sizeof("gray54")];
    char stringpool_str1165[sizeof("gray53")];
    char stringpool_str1169[sizeof("dark gray")];
    char stringpool_str1171[sizeof("gray52")];
    char stringpool_str1173[sizeof("gray51")];
    char stringpool_str1182[sizeof("paleturquoise4")];
    char stringpool_str1184[sizeof("paleturquoise3")];
    char stringpool_str1190[sizeof("paleturquoise2")];
    char stringpool_str1192[sizeof("paleturquoise1")];
    char stringpool_str1203[sizeof("pale goldenrod")];
    char stringpool_str1212[sizeof("turquoise")];
    char stringpool_str1213[sizeof("turquoise4")];
    char stringpool_str1214[sizeof("turquoise3")];
    char stringpool_str1217[sizeof("turquoise2")];
    char stringpool_str1218[sizeof("turquoise1")];
    char stringpool_str1219[sizeof("thistle4")];
    char stringpool_str1220[sizeof("wheat")];
    char stringpool_str1221[sizeof("thistle3")];
    char stringpool_str1222[sizeof("misty rose")];
    char stringpool_str1227[sizeof("thistle2")];
    char stringpool_str1229[sizeof("thistle1")];
    char stringpool_str1235[sizeof("chocolate")];
    char stringpool_str1236[sizeof("chocolate4")];
    char stringpool_str1237[sizeof("chocolate3")];
    char stringpool_str1238[sizeof("peachpuff4")];
    char stringpool_str1239[sizeof("peachpuff3")];
    char stringpool_str1240[sizeof("chocolate2")];
    char stringpool_str1241[sizeof("chocolate1")];
    char stringpool_str1242[sizeof("peachpuff2")];
    char stringpool_str1243[sizeof("peachpuff1")];
    char stringpool_str1248[sizeof("lightcoral")];
    char stringpool_str1249[sizeof("darkcyan")];
    char stringpool_str1250[sizeof("chartreuse")];
    char stringpool_str1251[sizeof("chartreuse4")];
    char stringpool_str1252[sizeof("chartreuse3")];
    char stringpool_str1255[sizeof("chartreuse2")];
    char stringpool_str1256[sizeof("chartreuse1")];
    char stringpool_str1257[sizeof("rosybrown4")];
    char stringpool_str1258[sizeof("rosybrown3")];
    char stringpool_str1259[sizeof("deepskyblue")];
    char stringpool_str1261[sizeof("rosybrown2")];
    char stringpool_str1262[sizeof("rosybrown1")];
    char stringpool_str1273[sizeof("peachpuff")];
    char stringpool_str1274[sizeof("cadetblue")];
    char stringpool_str1275[sizeof("cadetblue4")];
    char stringpool_str1276[sizeof("cadetblue3")];
    char stringpool_str1279[sizeof("cadetblue2")];
    char stringpool_str1280[sizeof("cadetblue1")];
    char stringpool_str1283[sizeof("mediumseagreen")];
    char stringpool_str1287[sizeof("light sea green")];
    char stringpool_str1291[sizeof("mediumpurple")];
    char stringpool_str1294[sizeof("light goldenrod")];
    char stringpool_str1296[sizeof("yellow4")];
    char stringpool_str1298[sizeof("yellow3")];
    char stringpool_str1299[sizeof("lawngreen")];
    char stringpool_str1301[sizeof("rosybrown")];
    char stringpool_str1304[sizeof("yellow2")];
    char stringpool_str1306[sizeof("yellow1")];
    char stringpool_str1316[sizeof("deepskyblue4")];
    char stringpool_str1318[sizeof("deepskyblue3")];
    char stringpool_str1320[sizeof("dark slate blue")];
    char stringpool_str1324[sizeof("deepskyblue2")];
    char stringpool_str1326[sizeof("deepskyblue1")];
    char stringpool_str1331[sizeof("navy")];
    char stringpool_str1343[sizeof("lightslategrey")];
    char stringpool_str1348[sizeof("mediumpurple4")];
    char stringpool_str1350[sizeof("mediumpurple3")];
    char stringpool_str1353[sizeof("olive drab")];
    char stringpool_str1356[sizeof("mediumpurple2")];
    char stringpool_str1358[sizeof("mediumpurple1")];
    char stringpool_str1359[sizeof("lightslategray")];
    char stringpool_str1367[sizeof("indian red")];
    char stringpool_str1369[sizeof("aquamarine")];
    char stringpool_str1370[sizeof("aquamarine4")];
    char stringpool_str1371[sizeof("aquamarine3")];
    char stringpool_str1374[sizeof("aquamarine2")];
    char stringpool_str1375[sizeof("aquamarine1")];
    char stringpool_str1376[sizeof("medium blue")];
    char stringpool_str1383[sizeof("orchid")];
    char stringpool_str1393[sizeof("dark sea green")];
    char stringpool_str1396[sizeof("khaki4")];
    char stringpool_str1398[sizeof("khaki3")];
    char stringpool_str1403[sizeof("mediumslateblue")];
    char stringpool_str1404[sizeof("khaki2")];
    char stringpool_str1406[sizeof("khaki1")];
    char stringpool_str1407[sizeof("black")];
    char stringpool_str1408[sizeof("lavender")];
    char stringpool_str1412[sizeof("burlywood")];
    char stringpool_str1413[sizeof("burlywood4")];
    char stringpool_str1414[sizeof("burlywood3")];
    char stringpool_str1417[sizeof("burlywood2")];
    char stringpool_str1418[sizeof("burlywood1")];
    char stringpool_str1426[sizeof("lightcyan4")];
    char stringpool_str1427[sizeof("lightcyan3")];
    char stringpool_str1429[sizeof("mediumspringgreen")];
    char stringpool_str1430[sizeof("lightcyan2")];
    char stringpool_str1431[sizeof("lightcyan1")];
    char stringpool_str1440[sizeof("orchid4")];
    char stringpool_str1442[sizeof("orchid3")];
    char stringpool_str1444[sizeof("alice blue")];
    char stringpool_str1448[sizeof("orchid2")];
    char stringpool_str1449[sizeof("powderblue")];
    char stringpool_str1450[sizeof("orchid1")];
    char stringpool_str1451[sizeof("lightskyblue")];
    char stringpool_str1458[sizeof("yellowgreen")];
    char stringpool_str1468[sizeof("greenyellow")];
    char stringpool_str1469[sizeof("white")];
    char stringpool_str1470[sizeof("lightcyan")];
    char stringpool_str1484[sizeof("sandybrown")];
    char stringpool_str1495[sizeof("grey0")];
    char stringpool_str1499[sizeof("navyblue")];
    char stringpool_str1506[sizeof("violet")];
    char stringpool_str1508[sizeof("lightskyblue4")];
    char stringpool_str1510[sizeof("lightskyblue3")];
    char stringpool_str1511[sizeof("gray0")];
    char stringpool_str1516[sizeof("lightskyblue2")];
    char stringpool_str1518[sizeof("lightskyblue1")];
    char stringpool_str1543[sizeof("violetred")];
    char stringpool_str1544[sizeof("violetred4")];
    char stringpool_str1545[sizeof("violetred3")];
    char stringpool_str1548[sizeof("violetred2")];
    char stringpool_str1549[sizeof("violetred1")];
    char stringpool_str1552[sizeof("grey40")];
    char stringpool_str1553[sizeof("grey30")];
    char stringpool_str1556[sizeof("grey20")];
    char stringpool_str1557[sizeof("grey10")];
    char stringpool_str1561[sizeof("light coral")];
    char stringpool_str1564[sizeof("dark slate grey")];
    char stringpool_str1566[sizeof("peach puff")];
    char stringpool_str1568[sizeof("gray40")];
    char stringpool_str1569[sizeof("gray30")];
    char stringpool_str1572[sizeof("gray20")];
    char stringpool_str1573[sizeof("gray10")];
    char stringpool_str1580[sizeof("dark slate gray")];
    char stringpool_str1583[sizeof("lawn green")];
    char stringpool_str1585[sizeof("rosy brown")];
    char stringpool_str1588[sizeof("lightyellow")];
    char stringpool_str1603[sizeof("cadet blue")];
    char stringpool_str1609[sizeof("medium sea green")];
    char stringpool_str1616[sizeof("blanchedalmond")];
    char stringpool_str1634[sizeof("dark cyan")];
    char stringpool_str1642[sizeof("mediumorchid")];
    char stringpool_str1678[sizeof("light slate blue")];
    char stringpool_str1686[sizeof("dark orchid")];
    char stringpool_str1697[sizeof("powder blue")];
    char stringpool_str1699[sizeof("mediumorchid4")];
    char stringpool_str1701[sizeof("mediumorchid3")];
    char stringpool_str1705[sizeof("medium purple")];
    char stringpool_str1707[sizeof("mediumorchid2")];
    char stringpool_str1709[sizeof("mediumorchid1")];
    char stringpool_str1725[sizeof("honeydew4")];
    char stringpool_str1727[sizeof("honeydew3")];
    char stringpool_str1733[sizeof("honeydew2")];
    char stringpool_str1734[sizeof("midnightblue")];
    char stringpool_str1735[sizeof("honeydew1")];
    char stringpool_str1739[sizeof("light slate grey")];
    char stringpool_str1742[sizeof("deeppink4")];
    char stringpool_str1744[sizeof("deeppink3")];
    char stringpool_str1747[sizeof("grey9")];
    char stringpool_str1750[sizeof("deeppink2")];
    char stringpool_str1752[sizeof("deeppink1")];
    char stringpool_str1754[sizeof("light cyan")];
    char stringpool_str1755[sizeof("light slate gray")];
    char stringpool_str1763[sizeof("gray9")];
    char stringpool_str1765[sizeof("grey8")];
    char stringpool_str1767[sizeof("light steel blue")];
    char stringpool_str1771[sizeof("grey7")];
    char stringpool_str1773[sizeof("dark turquoise")];
    char stringpool_str1777[sizeof("mintcream")];
    char stringpool_str1781[sizeof("gray8")];
    char stringpool_str1787[sizeof("gray7")];
    char stringpool_str1804[sizeof("grey49")];
    char stringpool_str1805[sizeof("grey39")];
    char stringpool_str1808[sizeof("grey29")];
    char stringpool_str1809[sizeof("grey19")];
    char stringpool_str1817[sizeof("moccasin")];
    char stringpool_str1820[sizeof("gray49")];
    char stringpool_str1821[sizeof("gray39")];
    char stringpool_str1822[sizeof("grey48")];
    char stringpool_str1823[sizeof("grey38")];
    char stringpool_str1824[sizeof("gray29")];
    char stringpool_str1825[sizeof("gray19")];
    char stringpool_str1826[sizeof("grey28")];
    char stringpool_str1827[sizeof("grey18")];
    char stringpool_str1828[sizeof("grey47")];
    char stringpool_str1829[sizeof("grey37")];
    char stringpool_str1830[sizeof("lightgoldenrodyellow")];
    char stringpool_str1832[sizeof("grey27")];
    char stringpool_str1833[sizeof("grey17")];
    char stringpool_str1838[sizeof("gray48")];
    char stringpool_str1839[sizeof("gray38")];
    char stringpool_str1842[sizeof("gray28")];
    char stringpool_str1843[sizeof("gray18")];
    char stringpool_str1844[sizeof("gray47")];
    char stringpool_str1845[sizeof("gray37")];
    char stringpool_str1848[sizeof("gray27")];
    char stringpool_str1849[sizeof("gray17")];
    char stringpool_str1858[sizeof("khaki")];
    char stringpool_str1866[sizeof("antiquewhite")];
    char stringpool_str1872[sizeof("violet red")];
    char stringpool_str1873[sizeof("mint cream")];
    char stringpool_str1876[sizeof("darkorchid")];
    char stringpool_str1877[sizeof("darkorchid4")];
    char stringpool_str1878[sizeof("darkorchid3")];
    char stringpool_str1881[sizeof("darkorchid2")];
    char stringpool_str1882[sizeof("darkorchid1")];
    char stringpool_str1884[sizeof("navy blue")];
    char stringpool_str1885[sizeof("grey6")];
    char stringpool_str1888[sizeof("yellow green")];
    char stringpool_str1901[sizeof("gray6")];
    char stringpool_str1908[sizeof("lightpink4")];
    char stringpool_str1909[sizeof("lightpink3")];
    char stringpool_str1912[sizeof("lightpink2")];
    char stringpool_str1913[sizeof("lightpink1")];
    char stringpool_str1923[sizeof("antiquewhite4")];
    char stringpool_str1925[sizeof("antiquewhite3")];
    char stringpool_str1931[sizeof("antiquewhite2")];
    char stringpool_str1933[sizeof("antiquewhite1")];
    char stringpool_str1942[sizeof("grey46")];
    char stringpool_str1943[sizeof("grey36")];
    char stringpool_str1946[sizeof("grey26")];
    char stringpool_str1947[sizeof("grey16")];
    char stringpool_str1948[sizeof("pale turquoise")];
    char stringpool_str1951[sizeof("grey5")];
    char stringpool_str1958[sizeof("gray46")];
    char stringpool_str1959[sizeof("gray36")];
    char stringpool_str1960[sizeof("yellow")];
    char stringpool_str1962[sizeof("gray26")];
    char stringpool_str1963[sizeof("gray16")];
    char stringpool_str1964[sizeof("medium slate blue")];
    char stringpool_str1967[sizeof("gray5")];
    char stringpool_str1968[sizeof("lavenderblush4")];
    char stringpool_str1970[sizeof("lavenderblush3")];
    char stringpool_str1976[sizeof("lavenderblush2")];
    char stringpool_str1978[sizeof("lavenderblush1")];
    char stringpool_str1985[sizeof("floral white")];
    char stringpool_str1987[sizeof("medium orchid")];
    char stringpool_str1989[sizeof("mediumturquoise")];
    char stringpool_str1991[sizeof("mediumaquamarine")];
    char stringpool_str1992[sizeof("light sky blue")];
    char stringpool_str1993[sizeof("hotpink4")];
    char stringpool_str1995[sizeof("hotpink3")];
    char stringpool_str2001[sizeof("hotpink2")];
    char stringpool_str2003[sizeof("hotpink1")];
    char stringpool_str2008[sizeof("grey45")];
    char stringpool_str2009[sizeof("grey35")];
    char stringpool_str2012[sizeof("grey25")];
    char stringpool_str2013[sizeof("grey15")];
    char stringpool_str2022[sizeof("light goldenrod yellow")];
    char stringpool_str2024[sizeof("gray45")];
    char stringpool_str2025[sizeof("gray35")];
    char stringpool_str2028[sizeof("gray25")];
    char stringpool_str2029[sizeof("gray15")];
    char stringpool_str2067[sizeof("antique white")];
    char stringpool_str2068[sizeof("deep sky blue")];
    char stringpool_str2093[sizeof("darkviolet")];
    char stringpool_str2107[sizeof("cornflowerblue")];
    char stringpool_str2119[sizeof("floralwhite")];
    char stringpool_str2130[sizeof("medium spring green")];
    char stringpool_str2141[sizeof("cornsilk4")];
    char stringpool_str2143[sizeof("cornsilk3")];
    char stringpool_str2149[sizeof("cornsilk2")];
    char stringpool_str2151[sizeof("cornsilk1")];
    char stringpool_str2161[sizeof("firebrick4")];
    char stringpool_str2162[sizeof("firebrick3")];
    char stringpool_str2165[sizeof("firebrick2")];
    char stringpool_str2166[sizeof("firebrick1")];
    char stringpool_str2176[sizeof("cornflower blue")];
    char stringpool_str2185[sizeof("blueviolet")];
    char stringpool_str2188[sizeof("midnight blue")];
    char stringpool_str2218[sizeof("blanched almond")];
    char stringpool_str2220[sizeof("darkolivegreen")];
    char stringpool_str2230[sizeof("lavenderblush")];
    char stringpool_str2232[sizeof("darkolivegreen4")];
    char stringpool_str2234[sizeof("darkolivegreen3")];
    char stringpool_str2236[sizeof("light pink")];
    char stringpool_str2240[sizeof("darkolivegreen2")];
    char stringpool_str2242[sizeof("darkolivegreen1")];
    char stringpool_str2247[sizeof("grey100")];
    char stringpool_str2248[sizeof("palevioletred")];
    char stringpool_str2260[sizeof("deeppink")];
    char stringpool_str2263[sizeof("gray100")];
    char stringpool_str2279[sizeof("white smoke")];
    char stringpool_str2305[sizeof("palevioletred4")];
    char stringpool_str2306[sizeof("ghostwhite")];
    char stringpool_str2307[sizeof("palevioletred3")];
    char stringpool_str2311[sizeof("grey90")];
    char stringpool_str2313[sizeof("palevioletred2")];
    char stringpool_str2315[sizeof("palevioletred1")];
    char stringpool_str2320[sizeof("grey80")];
    char stringpool_str2323[sizeof("grey70")];
    char stringpool_str2327[sizeof("gray90")];
    char stringpool_str2336[sizeof("gray80")];
    char stringpool_str2339[sizeof("gray70")];
    char stringpool_str2347[sizeof("lemonchiffon")];
    char stringpool_str2359[sizeof("lemonchiffon4")];
    char stringpool_str2361[sizeof("lemonchiffon3")];
    char stringpool_str2367[sizeof("lemonchiffon2")];
    char stringpool_str2369[sizeof("lemonchiffon1")];
    char stringpool_str2380[sizeof("grey60")];
    char stringpool_str2389[sizeof("honeydew")];
    char stringpool_str2396[sizeof("gray60")];
    char stringpool_str2398[sizeof("medium turquoise")];
    char stringpool_str2413[sizeof("grey50")];
    char stringpool_str2422[sizeof("dark violet")];
    char stringpool_str2427[sizeof("medium aquamarine")];
    char stringpool_str2429[sizeof("gray50")];
    char stringpool_str2464[sizeof("papaya whip")];
    char stringpool_str2482[sizeof("lightpink")];
    char stringpool_str2500[sizeof("ghost white")];
    char stringpool_str2511[sizeof("hotpink")];
    char stringpool_str2514[sizeof("blue violet")];
    char stringpool_str2525[sizeof("whitesmoke")];
    char stringpool_str2544[sizeof("green yellow")];
    char stringpool_str2562[sizeof("dark olive green")];
    char stringpool_str2563[sizeof("grey99")];
    char stringpool_str2572[sizeof("grey89")];
    char stringpool_str2575[sizeof("grey79")];
    char stringpool_str2579[sizeof("gray99")];
    char stringpool_str2581[sizeof("grey98")];
    char stringpool_str2587[sizeof("grey97")];
    char stringpool_str2588[sizeof("gray89")];
    char stringpool_str2590[sizeof("grey88")];
    char stringpool_str2591[sizeof("gray79")];
    char stringpool_str2593[sizeof("grey78")];
    char stringpool_str2596[sizeof("grey87")];
    char stringpool_str2597[sizeof("gray98")];
    char stringpool_str2599[sizeof("grey77")];
    char stringpool_str2603[sizeof("gray97")];
    char stringpool_str2606[sizeof("gray88")];
    char stringpool_str2609[sizeof("gray78")];
    char stringpool_str2612[sizeof("gray87")];
    char stringpool_str2615[sizeof("gray77")];
    char stringpool_str2632[sizeof("grey69")];
    char stringpool_str2645[sizeof("deep pink")];
    char stringpool_str2648[sizeof("gray69")];
    char stringpool_str2650[sizeof("grey68")];
    char stringpool_str2654[sizeof("papayawhip")];
    char stringpool_str2656[sizeof("grey67")];
    char stringpool_str2659[sizeof("cornsilk")];
    char stringpool_str2664[sizeof("light yellow")];
    char stringpool_str2665[sizeof("grey59")];
    char stringpool_str2666[sizeof("gray68")];
    char stringpool_str2672[sizeof("gray67")];
    char stringpool_str2681[sizeof("gray59")];
    char stringpool_str2683[sizeof("grey58")];
    char stringpool_str2684[sizeof("lavender blush")];
    char stringpool_str2689[sizeof("grey57")];
    char stringpool_str2699[sizeof("gray58")];
    char stringpool_str2701[sizeof("grey96")];
    char stringpool_str2705[sizeof("gray57")];
    char stringpool_str2710[sizeof("grey86")];
    char stringpool_str2713[sizeof("grey76")];
    char stringpool_str2714[sizeof("hot pink")];
    char stringpool_str2715[sizeof("lemon chiffon")];
    char stringpool_str2717[sizeof("gray96")];
    char stringpool_str2726[sizeof("gray86")];
    char stringpool_str2729[sizeof("gray76")];
    char stringpool_str2735[sizeof("firebrick")];
    char stringpool_str2767[sizeof("grey95")];
    char stringpool_str2770[sizeof("grey66")];
    char stringpool_str2776[sizeof("grey85")];
    char stringpool_str2779[sizeof("grey75")];
    char stringpool_str2783[sizeof("gray95")];
    char stringpool_str2786[sizeof("gray66")];
    char stringpool_str2791[sizeof("dark khaki")];
    char stringpool_str2792[sizeof("gray85")];
    char stringpool_str2795[sizeof("gray75")];
    char stringpool_str2803[sizeof("grey56")];
    char stringpool_str2819[sizeof("gray56")];
    char stringpool_str2836[sizeof("grey65")];
    char stringpool_str2839[sizeof("mediumvioletred")];
    char stringpool_str2852[sizeof("gray65")];
    char stringpool_str2869[sizeof("grey55")];
    char stringpool_str2879[sizeof("navajo white")];
    char stringpool_str2885[sizeof("gray55")];
    char stringpool_str2981[sizeof("darkkhaki")];
    char stringpool_str3013[sizeof("navajowhite")];
    char stringpool_str3019[sizeof("pale violet red")];
    char stringpool_str3070[sizeof("navajowhite4")];
    char stringpool_str3072[sizeof("navajowhite3")];
    char stringpool_str3078[sizeof("navajowhite2")];
    char stringpool_str3080[sizeof("navajowhite1")];
    char stringpool_str3478[sizeof("medium violet red")];
  };
static const struct stringpool_t stringpool_contents =
  {
    "red",
    "red4",
    "red3",
    "red2",
    "red1",
    "gold",
    "grey4",
    "grey3",
    "grey2",
    "grey1",
    "gray4",
    "gray3",
    "snow4",
    "snow3",
    "gray2",
    "gray1",
    "snow2",
    "snow1",
    "gold4",
    "gold3",
    "blue",
    "gold2",
    "gold1",
    "grey44",
    "grey34",
    "grey43",
    "grey33",
    "grey24",
    "grey14",
    "grey23",
    "grey13",
    "grey42",
    "grey32",
    "grey41",
    "grey31",
    "grey22",
    "grey12",
    "grey21",
    "grey11",
    "gray44",
    "gray34",
    "gray43",
    "gray33",
    "gray24",
    "gray14",
    "gray23",
    "gray13",
    "gray42",
    "gray32",
    "gray41",
    "gray31",
    "gray22",
    "gray12",
    "gray21",
    "gray11",
    "green",
    "orange",
    "blue4",
    "blue3",
    "azure",
    "blue2",
    "green4",
    "blue1",
    "green3",
    "green2",
    "green1",
    "darkred",
    "brown",
    "tan4",
    "tan3",
    "grey",
    "tan2",
    "tan1",
    "brown4",
    "sienna",
    "brown3",
    "brown2",
    "gray",
    "brown1",
    "orange4",
    "bisque",
    "orange3",
    "azure4",
    "azure3",
    "orange2",
    "orange1",
    "azure2",
    "azure1",
    "linen",
    "tan",
    "peru",
    "sienna4",
    "sienna3",
    "sienna2",
    "sienna1",
    "pink4",
    "pink3",
    "salmon",
    "pink2",
    "pink1",
    "bisque4",
    "salmon4",
    "bisque3",
    "salmon3",
    "bisque2",
    "salmon2",
    "bisque1",
    "salmon1",
    "plum4",
    "plum3",
    "purple",
    "plum2",
    "plum1",
    "orangered",
    "orangered4",
    "orangered3",
    "orangered2",
    "orangered1",
    "seagreen",
    "seagreen4",
    "purple4",
    "seagreen3",
    "purple3",
    "darkblue",
    "seagreen2",
    "purple2",
    "seagreen1",
    "purple1",
    "debianred",
    "darkorange",
    "darkorange4",
    "darkorange3",
    "darkorange2",
    "darkorange1",
    "darkgreen",
    "springgreen",
    "goldenrod",
    "goldenrod4",
    "goldenrod3",
    "goldenrod2",
    "goldenrod1",
    "springgreen4",
    "sea green",
    "springgreen3",
    "saddlebrown",
    "springgreen2",
    "springgreen1",
    "dodgerblue",
    "dodgerblue4",
    "dodgerblue3",
    "dodgerblue2",
    "dodgerblue1",
    "slateblue",
    "slateblue4",
    "slateblue3",
    "slateblue2",
    "slateblue1",
    "steelblue",
    "steelblue4",
    "steelblue3",
    "steelblue2",
    "steelblue1",
    "darkseagreen",
    "maroon",
    "plum",
    "darkseagreen4",
    "skyblue",
    "darkseagreen3",
    "maroon4",
    "darkgoldenrod",
    "maroon3",
    "darkseagreen2",
    "darkseagreen1",
    "maroon2",
    "maroon1",
    "lightgreen",
    "slategray4",
    "slategray3",
    "forestgreen",
    "slategray2",
    "slategray1",
    "palegreen4",
    "palegreen3",
    "palegreen2",
    "palegreen1",
    "skyblue4",
    "skyblue3",
    "darkgoldenrod4",
    "darkgoldenrod3",
    "skyblue2",
    "skyblue1",
    "sky blue",
    "darkgoldenrod2",
    "darkgoldenrod1",
    "palegreen",
    "dark red",
    "lightblue",
    "lightblue4",
    "lightblue3",
    "lightblue2",
    "lightblue1",
    "beige",
    "darkgrey",
    "darkmagenta",
    "darkgray",
    "magenta",
    "cyan",
    "royalblue",
    "royalblue4",
    "royalblue3",
    "royalblue2",
    "royalblue1",
    "darksalmon",
    "cyan4",
    "cyan3",
    "limegreen",
    "cyan2",
    "cyan1",
    "palegoldenrod",
    "orange red",
    "seashell",
    "tomato",
    "magenta4",
    "dodger blue",
    "magenta3",
    "dark green",
    "darkslateblue",
    "magenta2",
    "magenta1",
    "slategrey",
    "lightseagreen",
    "coral",
    "seashell4",
    "seashell3",
    "slategray",
    "seashell2",
    "seashell1",
    "lightgoldenrod",
    "tomato4",
    "tomato3",
    "dark orange",
    "tomato2",
    "tomato1",
    "coral4",
    "coral3",
    "coral2",
    "coral1",
    "mistyrose",
    "mistyrose4",
    "mistyrose3",
    "mistyrose2",
    "mistyrose1",
    "dark blue",
    "snow",
    "lightgoldenrod4",
    "lightgoldenrod3",
    "lightyellow4",
    "slate blue",
    "lightyellow3",
    "lightgoldenrod2",
    "lightgoldenrod1",
    "lightyellow2",
    "lightyellow1",
    "oldlace",
    "pink",
    "steel blue",
    "dimgrey",
    "lightsalmon",
    "darkturquoise",
    "dimgray",
    "lightsalmon4",
    "lightsalmon3",
    "lightsalmon2",
    "lightsalmon1",
    "saddle brown",
    "spring green",
    "slate grey",
    "lightgrey",
    "light green",
    "dim grey",
    "slate gray",
    "lightgray",
    "ivory4",
    "pale green",
    "ivory3",
    "darkslategray4",
    "darkslategray3",
    "ivory2",
    "dim gray",
    "ivory1",
    "darkslategray2",
    "darkslategray1",
    "old lace",
    "olivedrab4",
    "olivedrab3",
    "dark goldenrod",
    "olivedrab2",
    "olivedrab1",
    "olivedrab",
    "indianred",
    "indianred4",
    "indianred3",
    "lightsteelblue",
    "indianred2",
    "indianred1",
    "grey94",
    "gainsboro",
    "grey93",
    "grey92",
    "grey84",
    "grey91",
    "grey83",
    "grey74",
    "grey73",
    "gray94",
    "grey82",
    "gray93",
    "grey81",
    "grey72",
    "grey71",
    "gray92",
    "gray84",
    "gray91",
    "gray83",
    "gray74",
    "light blue",
    "gray73",
    "gray82",
    "gray81",
    "gray72",
    "gray71",
    "lightslateblue",
    "sandy brown",
    "lime green",
    "lightsteelblue4",
    "lightsteelblue3",
    "lightsteelblue2",
    "forest green",
    "lightsteelblue1",
    "dark salmon",
    "grey64",
    "aliceblue",
    "grey63",
    "darkslategrey",
    "grey62",
    "royal blue",
    "grey61",
    "paleturquoise",
    "dark magenta",
    "mediumblue",
    "gray64",
    "gray63",
    "ivory",
    "light grey",
    "darkslategray",
    "gray62",
    "gray61",
    "wheat4",
    "wheat3",
    "light salmon",
    "grey54",
    "grey53",
    "wheat2",
    "light gray",
    "wheat1",
    "dark grey",
    "grey52",
    "grey51",
    "thistle",
    "gray54",
    "gray53",
    "dark gray",
    "gray52",
    "gray51",
    "paleturquoise4",
    "paleturquoise3",
    "paleturquoise2",
    "paleturquoise1",
    "pale goldenrod",
    "turquoise",
    "turquoise4",
    "turquoise3",
    "turquoise2",
    "turquoise1",
    "thistle4",
    "wheat",
    "thistle3",
    "misty rose",
    "thistle2",
    "thistle1",
    "chocolate",
    "chocolate4",
    "chocolate3",
    "peachpuff4",
    "peachpuff3",
    "chocolate2",
    "chocolate1",
    "peachpuff2",
    "peachpuff1",
    "lightcoral",
    "darkcyan",
    "chartreuse",
    "chartreuse4",
    "chartreuse3",
    "chartreuse2",
    "chartreuse1",
    "rosybrown4",
    "rosybrown3",
    "deepskyblue",
    "rosybrown2",
    "rosybrown1",
    "peachpuff",
    "cadetblue",
    "cadetblue4",
    "cadetblue3",
    "cadetblue2",
    "cadetblue1",
    "mediumseagreen",
    "light sea green",
    "mediumpurple",
    "light goldenrod",
    "yellow4",
    "yellow3",
    "lawngreen",
    "rosybrown",
    "yellow2",
    "yellow1",
    "deepskyblue4",
    "deepskyblue3",
    "dark slate blue",
    "deepskyblue2",
    "deepskyblue1",
    "navy",
    "lightslategrey",
    "mediumpurple4",
    "mediumpurple3",
    "olive drab",
    "mediumpurple2",
    "mediumpurple1",
    "lightslategray",
    "indian red",
    "aquamarine",
    "aquamarine4",
    "aquamarine3",
    "aquamarine2",
    "aquamarine1",
    "medium blue",
    "orchid",
    "dark sea green",
    "khaki4",
    "khaki3",
    "mediumslateblue",
    "khaki2",
    "khaki1",
    "black",
    "lavender",
    "burlywood",
    "burlywood4",
    "burlywood3",
    "burlywood2",
    "burlywood1",
    "lightcyan4",
    "lightcyan3",
    "mediumspringgreen",
    "lightcyan2",
    "lightcyan1",
    "orchid4",
    "orchid3",
    "alice blue",
    "orchid2",
    "powderblue",
    "orchid1",
    "lightskyblue",
    "yellowgreen",
    "greenyellow",
    "white",
    "lightcyan",
    "sandybrown",
    "grey0",
    "navyblue",
    "violet",
    "lightskyblue4",
    "lightskyblue3",
    "gray0",
    "lightskyblue2",
    "lightskyblue1",
    "violetred",
    "violetred4",
    "violetred3",
    "violetred2",
    "violetred1",
    "grey40",
    "grey30",
    "grey20",
    "grey10",
    "light coral",
    "dark slate grey",
    "peach puff",
    "gray40",
    "gray30",
    "gray20",
    "gray10",
    "dark slate gray",
    "lawn green",
    "rosy brown",
    "lightyellow",
    "cadet blue",
    "medium sea green",
    "blanchedalmond",
    "dark cyan",
    "mediumorchid",
    "light slate blue",
    "dark orchid",
    "powder blue",
    "mediumorchid4",
    "mediumorchid3",
    "medium purple",
    "mediumorchid2",
    "mediumorchid1",
    "honeydew4",
    "honeydew3",
    "honeydew2",
    "midnightblue",
    "honeydew1",
    "light slate grey",
    "deeppink4",
    "deeppink3",
    "grey9",
    "deeppink2",
    "deeppink1",
    "light cyan",
    "light slate gray",
    "gray9",
    "grey8",
    "light steel blue",
    "grey7",
    "dark turquoise",
    "mintcream",
    "gray8",
    "gray7",
    "grey49",
    "grey39",
    "grey29",
    "grey19",
    "moccasin",
    "gray49",
    "gray39",
    "grey48",
    "grey38",
    "gray29",
    "gray19",
    "grey28",
    "grey18",
    "grey47",
    "grey37",
    "lightgoldenrodyellow",
    "grey27",
    "grey17",
    "gray48",
    "gray38",
    "gray28",
    "gray18",
    "gray47",
    "gray37",
    "gray27",
    "gray17",
    "khaki",
    "antiquewhite",
    "violet red",
    "mint cream",
    "darkorchid",
    "darkorchid4",
    "darkorchid3",
    "darkorchid2",
    "darkorchid1",
    "navy blue",
    "grey6",
    "yellow green",
    "gray6",
    "lightpink4",
    "lightpink3",
    "lightpink2",
    "lightpink1",
    "antiquewhite4",
    "antiquewhite3",
    "antiquewhite2",
    "antiquewhite1",
    "grey46",
    "grey36",
    "grey26",
    "grey16",
    "pale turquoise",
    "grey5",
    "gray46",
    "gray36",
    "yellow",
    "gray26",
    "gray16",
    "medium slate blue",
    "gray5",
    "lavenderblush4",
    "lavenderblush3",
    "lavenderblush2",
    "lavenderblush1",
    "floral white",
    "medium orchid",
    "mediumturquoise",
    "mediumaquamarine",
    "light sky blue",
    "hotpink4",
    "hotpink3",
    "hotpink2",
    "hotpink1",
    "grey45",
    "grey35",
    "grey25",
    "grey15",
    "light goldenrod yellow",
    "gray45",
    "gray35",
    "gray25",
    "gray15",
    "antique white",
    "deep sky blue",
    "darkviolet",
    "cornflowerblue",
    "floralwhite",
    "medium spring green",
    "cornsilk4",
    "cornsilk3",
    "cornsilk2",
    "cornsilk1",
    "firebrick4",
    "firebrick3",
    "firebrick2",
    "firebrick1",
    "cornflower blue",
    "blueviolet",
    "midnight blue",
    "blanched almond",
    "darkolivegreen",
    "lavenderblush",
    "darkolivegreen4",
    "darkolivegreen3",
    "light pink",
    "darkolivegreen2",
    "darkolivegreen1",
    "grey100",
    "palevioletred",
    "deeppink",
    "gray100",
    "white smoke",
    "palevioletred4",
    "ghostwhite",
    "palevioletred3",
    "grey90",
    "palevioletred2",
    "palevioletred1",
    "grey80",
    "grey70",
    "gray90",
    "gray80",
    "gray70",
    "lemonchiffon",
    "lemonchiffon4",
    "lemonchiffon3",
    "lemonchiffon2",
    "lemonchiffon1",
    "grey60",
    "honeydew",
    "gray60",
    "medium turquoise",
    "grey50",
    "dark violet",
    "medium aquamarine",
    "gray50",
    "papaya whip",
    "lightpink",
    "ghost white",
    "hotpink",
    "blue violet",
    "whitesmoke",
    "green yellow",
    "dark olive green",
    "grey99",
    "grey89",
    "grey79",
    "gray99",
    "grey98",
    "grey97",
    "gray89",
    "grey88",
    "gray79",
    "grey78",
    "grey87",
    "gray98",
    "grey77",
    "gray97",
    "gray88",
    "gray78",
    "gray87",
    "gray77",
    "grey69",
    "deep pink",
    "gray69",
    "grey68",
    "papayawhip",
    "grey67",
    "cornsilk",
    "light yellow",
    "grey59",
    "gray68",
    "gray67",
    "gray59",
    "grey58",
    "lavender blush",
    "grey57",
    "gray58",
    "grey96",
    "gray57",
    "grey86",
    "grey76",
    "hot pink",
    "lemon chiffon",
    "gray96",
    "gray86",
    "gray76",
    "firebrick",
    "grey95",
    "grey66",
    "grey85",
    "grey75",
    "gray95",
    "gray66",
    "dark khaki",
    "gray85",
    "gray75",
    "grey56",
    "gray56",
    "grey65",
    "mediumvioletred",
    "gray65",
    "grey55",
    "navajo white",
    "gray55",
    "darkkhaki",
    "navajowhite",
    "pale violet red",
    "navajowhite4",
    "navajowhite3",
    "navajowhite2",
    "navajowhite1",
    "medium violet red"
  };
#define stringpool ((const char *) &stringpool_contents)

#if (defined __GNUC__ && __GNUC__ + (__GNUC_MINOR__ >= 6) > 4) || (defined __clang__ && __clang_major__ >= 3)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wmissing-field-initializers"
#endif
static const struct Keyword color_names[] =
  {
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1},
#line 635 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str172, 16711680},
#line 639 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str173, 9109504},
#line 638 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str174, 13434880},
    {-1}, {-1},
#line 637 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str177, 15597568},
#line 636 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str178, 16711680},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 177 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str202, 16766720},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 332 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str229, 657930},
    {-1},
#line 321 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str231, 526344},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 310 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str237, 328965},
    {-1},
#line 298 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str239, 197379},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 223 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str245, 657930},
    {-1},
#line 212 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str247, 526344},
#line 701 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str248, 9144713},
    {-1},
#line 700 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str250, 13486537},
    {-1}, {-1},
#line 201 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str253, 328965},
    {-1},
#line 189 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str255, 197379},
#line 699 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str256, 15657449},
    {-1},
#line 698 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str258, 16775930},
#line 181 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str259, 9139456},
    {-1},
#line 180 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str261, 13479168},
    {-1}, {-1}, {-1},
#line 30 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str265, 255},
    {-1},
#line 179 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str267, 15649024},
    {-1},
#line 178 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str269, 16766720},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 337 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str286, 7368816},
#line 326 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str287, 5723991},
#line 336 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str288, 7237230},
#line 325 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str289, 5526612},
#line 315 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str290, 4013373},
#line 304 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str291, 2368548},
#line 314 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str292, 3881787},
#line 303 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str293, 2171169},
#line 335 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str294, 7039851},
#line 324 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str295, 5395026},
#line 334 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str296, 6908265},
#line 323 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str297, 5197647},
#line 313 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str298, 3684408},
#line 302 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str299, 2039583},
#line 312 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str300, 3552822},
#line 301 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str301, 1842204},
#line 228 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str302, 7368816},
#line 217 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str303, 5723991},
#line 227 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str304, 7237230},
#line 216 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str305, 5526612},
#line 206 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str306, 4013373},
#line 195 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str307, 2368548},
#line 205 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str308, 3881787},
#line 194 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str309, 2171169},
#line 226 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str310, 7039851},
#line 215 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str311, 5395026},
#line 225 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str312, 6908265},
#line 214 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str313, 5197647},
#line 204 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str314, 3684408},
#line 193 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str315, 2039583},
#line 203 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str316, 3552822},
#line 192 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str317, 1842204},
    {-1},
#line 289 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str319, 65280},
    {-1},
#line 573 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str321, 16753920},
#line 35 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str322, 139},
    {-1},
#line 34 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str324, 205},
    {-1},
#line 16 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str326, 15794175},
    {-1}, {-1}, {-1},
#line 33 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str330, 238},
#line 294 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str331, 35584},
#line 32 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str332, 255},
#line 293 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str333, 52480},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 292 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str339, 60928},
    {-1},
#line 291 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str341, 65280},
    {-1}, {-1}, {-1},
#line 126 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str345, 9109504},
    {-1}, {-1}, {-1}, {-1},
#line 37 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str350, 10824234},
    {-1},
#line 718 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str352, 9132587},
#line 717 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str353, 13468991},
    {-1},
#line 296 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str355, 12500670},
#line 716 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str356, 15637065},
#line 715 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str357, 16753999},
    {-1}, {-1}, {-1}, {-1},
#line 41 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str362, 9118499},
#line 672 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str363, 10506797},
#line 40 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str364, 13447987},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 39 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str370, 15612731},
#line 187 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str371, 12500670},
#line 38 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str372, 16728128},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 578 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str378, 9132544},
#line 22 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str379, 16770244},
#line 577 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str380, 13468928},
    {-1}, {-1},
#line 20 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str383, 8620939},
    {-1},
#line 19 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str385, 12701133},
#line 576 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str386, 15636992},
    {-1},
#line 575 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str388, 16753920},
    {-1}, {-1},
#line 18 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str391, 14741230},
    {-1},
#line 17 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str393, 15794175},
#line 508 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str394, 16445670},
    {-1},
#line 714 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str396, 13808780},
    {-1}, {-1}, {-1},
#line 617 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str400, 13468991},
    {-1}, {-1}, {-1},
#line 676 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str404, 9127718},
    {-1},
#line 675 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str406, 13461561},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 674 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str412, 15628610},
    {-1},
#line 673 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str414, 16745031},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 622 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str420, 9134956},
    {-1},
#line 621 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str422, 13472158},
    {-1}, {-1},
#line 654 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str425, 16416882},
    {-1}, {-1},
#line 620 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str428, 15641016},
    {-1},
#line 619 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str430, 16758213},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 26 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str436, 9141611},
#line 658 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str437, 9129017},
#line 25 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str438, 13481886},
#line 657 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str439, 13463636},
    {-1}, {-1}, {-1}, {-1},
#line 24 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str444, 15652279},
#line 656 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str445, 15630946},
#line 23 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str446, 16770244},
#line 655 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str447, 16747625},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 627 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str456, 9135755},
    {-1},
#line 626 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str458, 13473485},
    {-1}, {-1}, {-1}, {-1},
#line 630 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str463, 10494192},
#line 625 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str464, 15642350},
    {-1},
#line 624 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str466, 16759807},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 579 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str493, 16729344},
#line 583 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str494, 9118976},
#line 582 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str495, 13448960},
    {-1}, {-1},
#line 581 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str498, 15613952},
#line 580 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str499, 16729344},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 662 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str507, 3050327},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1},
#line 666 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str519, 3050327},
#line 634 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str520, 5577355},
#line 665 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str521, 4443520},
#line 633 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str522, 8201933},
    {-1},
#line 99 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str524, 139},
    {-1}, {-1},
#line 664 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str527, 5172884},
#line 632 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str528, 9514222},
#line 663 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str529, 5570463},
#line 631 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str530, 10170623},
#line 142 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str531, 14092113},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 116 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str540, 16747520},
#line 120 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str541, 9127168},
#line 119 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str542, 13460992},
    {-1}, {-1},
#line 118 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str545, 15627776},
#line 117 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str546, 16744192},
    {-1}, {-1},
#line 107 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str549, 25600},
    {-1},
#line 703 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str551, 65407},
#line 182 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str552, 14329120},
#line 186 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str553, 9136404},
#line 185 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str554, 13474589},
    {-1}, {-1},
#line 184 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str557, 15643682},
#line 183 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str558, 16761125},
    {-1}, {-1}, {-1}, {-1},
#line 707 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str563, 35653},
#line 661 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str564, 3050327},
#line 706 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str565, 52582},
#line 653 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str566, 9127187},
    {-1}, {-1}, {-1}, {-1},
#line 705 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str571, 61046},
    {-1},
#line 704 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str573, 65407},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 160 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str582, 2003199},
#line 164 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str583, 1068683},
#line 163 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str584, 1602765},
    {-1}, {-1},
#line 162 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str587, 1869550},
#line 161 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str588, 2003199},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 686 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str596, 6970061},
#line 690 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str597, 4668555},
#line 689 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str598, 6904269},
    {-1}, {-1},
#line 688 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str601, 8021998},
#line 687 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str602, 8613887},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 709 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str610, 4620980},
#line 713 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str611, 3564683},
#line 712 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str612, 5215437},
    {-1}, {-1},
#line 711 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str615, 6073582},
#line 710 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str616, 6535423},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 128 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str624, 9419919},
    {-1}, {-1}, {-1}, {-1},
#line 514 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str629, 11546720},
    {-1}, {-1},
#line 623 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str632, 14524637},
    {-1}, {-1}, {-1},
#line 132 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str636, 6916969},
#line 678 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str637, 8900331},
#line 131 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str638, 10210715},
    {-1}, {-1},
#line 518 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str641, 9116770},
#line 101 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str642, 12092939},
#line 517 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str643, 13445520},
#line 130 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str644, 11857588},
    {-1},
#line 129 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str646, 12713921},
    {-1}, {-1},
#line 516 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str649, 15610023},
    {-1},
#line 515 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str651, 16725171},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 475 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str669, 9498256},
    {-1}, {-1}, {-1}, {-1},
#line 695 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str674, 7109515},
#line 694 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str675, 10467021},
    {-1},
#line 173 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str677, 2263842},
#line 693 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str678, 12178414},
#line 692 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str679, 13034239},
#line 598 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str680, 5540692},
#line 597 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str681, 8179068},
    {-1}, {-1},
#line 596 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str684, 9498256},
#line 595 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str685, 10157978},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 682 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str694, 4878475},
    {-1},
#line 681 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str696, 7120589},
    {-1}, {-1},
#line 105 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str699, 9135368},
    {-1},
#line 104 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str701, 13473036},
#line 680 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str702, 8306926},
    {-1},
#line 679 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str704, 8900351},
    {-1},
#line 677 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str706, 8900331},
#line 103 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str707, 15641870},
    {-1},
#line 102 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str709, 16759055},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 594 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str724, 10025880},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 91 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str730, 9109504},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 457 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str745, 11393254},
#line 461 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str746, 6849419},
#line 460 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str747, 10141901},
    {-1}, {-1},
#line 459 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str750, 11722734},
#line 458 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str751, 12578815},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 21 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str760, 16119260},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 108 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str768, 11119017},
    {-1},
#line 110 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str770, 9109643},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1},
#line 106 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str784, 11119017},
    {-1}, {-1}, {-1},
#line 509 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str788, 16711935},
    {-1}, {-1}, {-1},
#line 75 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str792, 65535},
    {-1},
#line 647 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str794, 4286945},
#line 651 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str795, 2572427},
#line 650 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str796, 3825613},
    {-1}, {-1},
#line 649 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str799, 4419310},
#line 648 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str800, 4749055},
    {-1},
#line 127 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str802, 15308410},
    {-1},
#line 79 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str804, 35723},
    {-1},
#line 78 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str806, 52685},
    {-1}, {-1}, {-1}, {-1},
#line 507 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str811, 3329330},
#line 77 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str812, 61166},
    {-1},
#line 76 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str814, 65535},
    {-1}, {-1},
#line 593 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str817, 15657130},
    {-1}, {-1}, {-1}, {-1},
#line 574 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str822, 16729344},
    {-1}, {-1},
#line 667 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str825, 16774638},
    {-1},
#line 724 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str827, 16737095},
    {-1},
#line 513 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str829, 9109643},
#line 159 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str830, 2003199},
#line 512 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str831, 13435085},
    {-1},
#line 84 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str833, 25600},
    {-1}, {-1},
#line 133 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str836, 4734347},
#line 511 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str837, 15597806},
    {-1},
#line 510 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str839, 16711935},
#line 696 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str840, 7372944},
    {-1}, {-1}, {-1},
#line 487 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str844, 2142890},
    {-1}, {-1}, {-1}, {-1},
#line 63 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str849, 16744272},
    {-1}, {-1},
#line 671 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str852, 9143938},
    {-1},
#line 670 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str854, 13485503},
    {-1},
#line 691 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str856, 7372944},
    {-1}, {-1}, {-1},
#line 669 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str860, 15656414},
    {-1},
#line 668 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str862, 16774638},
    {-1},
#line 468 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str864, 15654274},
#line 728 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str865, 9123366},
    {-1},
#line 727 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str867, 13455161},
    {-1},
#line 89 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str869, 16747520},
    {-1}, {-1}, {-1},
#line 726 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str873, 15621186},
    {-1},
#line 725 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str875, 16737095},
#line 67 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str876, 9125423},
    {-1},
#line 66 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str878, 13458245},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 65 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str884, 15624784},
    {-1},
#line 64 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str886, 16740950},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 550 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str893, 16770273},
#line 554 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str894, 9141627},
#line 553 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str895, 13481909},
    {-1}, {-1},
#line 552 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str898, 15652306},
#line 551 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str899, 16770273},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 80 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str909, 139},
    {-1}, {-1},
#line 697 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str912, 16775930},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 472 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str921, 9142604},
    {-1},
#line 471 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str923, 13483632},
#line 505 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str924, 9145210},
#line 683 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str925, 6970061},
#line 504 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str926, 13487540},
    {-1}, {-1},
#line 470 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str929, 15654018},
    {-1},
#line 469 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str931, 16772235},
#line 503 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str932, 15658705},
    {-1},
#line 502 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str934, 16777184},
    {-1}, {-1},
#line 566 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str937, 16643558},
#line 618 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str938, 16761035},
#line 708 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str939, 4620980},
    {-1}, {-1}, {-1},
#line 158 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str943, 6908265},
    {-1}, {-1}, {-1}, {-1},
#line 482 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str948, 16752762},
    {-1},
#line 140 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str950, 52945},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 157 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str959, 6908265},
#line 486 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str960, 9131842},
    {-1},
#line 485 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str962, 13468002},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 484 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str968, 15635826},
    {-1},
#line 483 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str970, 16752762},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 652 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str977, 9127187},
    {-1}, {-1}, {-1},
#line 702 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str981, 65407},
    {-1}, {-1}, {-1}, {-1},
#line 685 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str986, 7372944},
    {-1}, {-1},
#line 476 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str989, 13882323},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 446 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str998, 9498256},
    {-1},
#line 156 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1000, 6908265},
    {-1},
#line 684 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1002, 7372944},
    {-1}, {-1},
#line 474 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1005, 13882323},
    {-1},
#line 419 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1007, 9145219},
#line 590 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1008, 10025880},
#line 418 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1009, 13487553},
    {-1},
#line 138 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1011, 5409675},
    {-1},
#line 137 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1013, 7982541},
    {-1},
#line 417 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1015, 15658720},
#line 155 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1016, 6908265},
#line 416 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1017, 16777200},
    {-1},
#line 136 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1019, 9301742},
    {-1},
#line 135 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1021, 9961471},
    {-1}, {-1},
#line 565 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1024, 16643558},
#line 572 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1025, 6916898},
#line 571 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1026, 10145074},
    {-1},
#line 82 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1028, 12092939},
#line 570 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1029, 11791930},
#line 569 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1030, 12648254},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 568 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1036, 7048739},
    {-1},
#line 410 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1038, 13458524},
#line 414 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1039, 9124410},
#line 413 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1040, 13456725},
#line 496 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1041, 11584734},
    {-1},
#line 412 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1043, 15623011},
#line 411 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1044, 16738922},
#line 392 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1045, 15790320},
#line 174 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1046, 14474460},
#line 391 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1047, 15592941},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 390 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1053, 15461355},
#line 381 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1054, 14079702},
#line 389 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1055, 15263976},
#line 380 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1056, 13948116},
#line 370 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1057, 12434877},
    {-1},
#line 369 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1059, 12237498},
    {-1},
#line 283 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1061, 15790320},
#line 379 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1062, 13750737},
#line 282 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1063, 15592941},
#line 378 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1064, 13619151},
#line 368 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1065, 12105912},
    {-1},
#line 367 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1067, 11908533},
    {-1},
#line 281 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1069, 15461355},
#line 272 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1070, 14079702},
#line 280 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1071, 15263976},
#line 271 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1072, 13948116},
#line 261 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1073, 12434877},
#line 440 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1074, 11393254},
#line 260 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1075, 12237498},
    {-1}, {-1},
#line 270 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1078, 13750737},
    {-1},
#line 269 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1080, 13619151},
#line 259 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1081, 12105912},
    {-1},
#line 258 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1083, 11908533},
    {-1}, {-1}, {-1},
#line 493 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1087, 8679679},
    {-1}, {-1}, {-1}, {-1},
#line 659 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1092, 16032864},
    {-1}, {-1},
#line 506 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1095, 3329330},
    {-1}, {-1},
#line 500 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1098, 7240587},
    {-1},
#line 499 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1100, 10663373},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 498 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1106, 12374766},
#line 172 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1107, 2263842},
#line 497 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1108, 13296127},
    {-1}, {-1}, {-1},
#line 92 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1112, 15308410},
    {-1},
#line 359 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1114, 10724259},
#line 4 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1115, 15792383},
#line 358 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1116, 10592673},
    {-1}, {-1}, {-1}, {-1},
#line 139 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1121, 3100495},
#line 357 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1122, 10395294},
#line 646 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1123, 4286945},
#line 356 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1124, 10263708},
#line 599 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1125, 11529966},
#line 87 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1126, 9109643},
    {-1},
#line 529 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1128, 205},
    {-1},
#line 250 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1130, 10724259},
    {-1},
#line 249 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1132, 10592673},
#line 415 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1133, 16777200},
    {-1},
#line 447 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1135, 13882323},
    {-1},
#line 134 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1137, 3100495},
#line 248 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1138, 10395294},
    {-1},
#line 247 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1140, 10263708},
    {-1},
#line 745 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1142, 9141862},
    {-1},
#line 744 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1144, 13482646},
#line 449 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1145, 16752762},
    {-1},
#line 348 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1147, 9079434},
    {-1},
#line 347 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1149, 8882055},
#line 743 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1150, 15653038},
#line 445 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1151, 13882323},
#line 742 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1152, 16771002},
#line 85 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1153, 11119017},
    {-1},
#line 346 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1155, 8750469},
    {-1},
#line 345 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1157, 8553090},
    {-1}, {-1}, {-1}, {-1},
#line 719 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1162, 14204888},
#line 239 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1163, 9079434},
    {-1},
#line 238 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1165, 8882055},
    {-1}, {-1}, {-1},
#line 83 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1169, 11119017},
    {-1},
#line 237 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1171, 8750469},
    {-1},
#line 236 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1173, 8553090},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 603 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1182, 6720395},
    {-1},
#line 602 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1184, 9883085},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 601 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1190, 11464430},
    {-1},
#line 600 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1192, 12320767},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1},
#line 589 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1203, 15657130},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 729 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1212, 4251856},
#line 733 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1213, 34443},
#line 732 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1214, 50637},
    {-1}, {-1},
#line 731 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1217, 58862},
#line 730 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1218, 62975},
#line 723 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1219, 9141131},
#line 741 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1220, 16113331},
#line 722 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1221, 13481421},
#line 549 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1222, 16770273},
    {-1}, {-1}, {-1}, {-1},
#line 721 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1227, 15651566},
    {-1},
#line 720 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1229, 16769535},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 58 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1235, 13789470},
#line 62 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1236, 9127187},
#line 61 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1237, 13461021},
#line 616 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1238, 9140069},
#line 615 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1239, 13479829},
#line 60 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1240, 15627809},
#line 59 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1241, 16744228},
#line 614 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1242, 15649709},
#line 613 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1243, 16767673},
    {-1}, {-1}, {-1}, {-1},
#line 462 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1248, 15761536},
#line 100 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1249, 35723},
#line 53 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1250, 8388352},
#line 57 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1251, 4557568},
#line 56 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1252, 6737152},
    {-1}, {-1},
#line 55 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1255, 7794176},
#line 54 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1256, 8388352},
#line 645 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1257, 9136489},
#line 644 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1258, 13474715},
#line 150 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1259, 49151},
    {-1},
#line 643 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1261, 15643828},
#line 642 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1262, 16761281},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1},
#line 612 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1273, 16767673},
#line 48 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1274, 6266528},
#line 52 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1275, 5473931},
#line 51 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1276, 8046029},
    {-1}, {-1},
#line 50 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1279, 9364974},
#line 49 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1280, 10024447},
    {-1}, {-1},
#line 540 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1283, 3978097},
    {-1}, {-1}, {-1},
#line 450 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1287, 2142890},
    {-1}, {-1}, {-1},
#line 535 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1291, 9662683},
    {-1}, {-1},
#line 443 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1294, 15654274},
    {-1},
#line 754 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1296, 9145088},
    {-1},
#line 753 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1298, 13487360},
#line 433 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1299, 8190976},
    {-1},
#line 641 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1301, 12357519},
    {-1}, {-1},
#line 752 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1304, 15658496},
    {-1},
#line 751 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1306, 16776960},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 154 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1316, 26763},
    {-1},
#line 153 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1318, 39629},
    {-1},
#line 94 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1320, 4734347},
    {-1}, {-1}, {-1},
#line 152 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1324, 45806},
    {-1},
#line 151 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1326, 49151},
    {-1}, {-1}, {-1}, {-1},
#line 562 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1331, 128},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1},
#line 495 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1343, 7833753},
    {-1}, {-1}, {-1}, {-1},
#line 539 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1348, 6113163},
    {-1},
#line 538 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1350, 9005261},
    {-1}, {-1},
#line 567 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1353, 7048739},
    {-1}, {-1},
#line 537 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1356, 10451438},
    {-1},
#line 536 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1358, 11240191},
#line 494 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1359, 7833753},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 409 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1367, 13458524},
    {-1},
#line 11 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1369, 8388564},
#line 15 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1370, 4557684},
#line 14 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1371, 6737322},
    {-1}, {-1},
#line 13 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1374, 7794374},
#line 12 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1375, 8388564},
#line 520 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1376, 205},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 584 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1383, 14315734},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 93 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1393, 9419919},
    {-1}, {-1},
#line 424 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1396, 9143886},
    {-1},
#line 423 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1398, 13485683},
    {-1}, {-1}, {-1}, {-1},
#line 541 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1403, 8087790},
#line 422 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1404, 15656581},
    {-1},
#line 421 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1406, 16774799},
#line 27 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1407, 0},
#line 425 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1408, 15132410},
    {-1}, {-1}, {-1},
#line 42 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1412, 14596231},
#line 46 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1413, 9139029},
#line 45 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1414, 13478525},
    {-1}, {-1},
#line 44 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1417, 15648145},
#line 43 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1418, 16765851},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 467 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1426, 8031115},
#line 466 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1427, 11849165},
    {-1},
#line 542 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1429, 64154},
#line 465 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1430, 13758190},
#line 464 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1431, 14745599},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 588 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1440, 9127817},
    {-1},
#line 587 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1442, 13461961},
    {-1},
#line 3 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1444, 15792383},
    {-1}, {-1}, {-1},
#line 586 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1448, 15629033},
#line 629 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1449, 11591910},
#line 585 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1450, 16745466},
#line 488 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1451, 8900346},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 755 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1458, 10145074},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 295 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1468, 11403055},
#line 746 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1469, 16777215},
#line 463 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1470, 14745599},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1},
#line 660 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1484, 16032864},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1},
#line 297 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1495, 0},
    {-1}, {-1}, {-1},
#line 564 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1499, 128},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 734 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1506, 15631086},
    {-1},
#line 492 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1508, 6323083},
    {-1},
#line 491 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1510, 9287373},
#line 188 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1511, 0},
    {-1}, {-1}, {-1}, {-1},
#line 490 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1516, 10802158},
    {-1},
#line 489 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1518, 11592447},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 736 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1543, 13639824},
#line 740 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1544, 9118290},
#line 739 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1545, 13447800},
    {-1}, {-1},
#line 738 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1548, 15612556},
#line 737 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1549, 16727702},
    {-1}, {-1},
#line 333 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1552, 6710886},
#line 322 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1553, 5066061},
    {-1}, {-1},
#line 311 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1556, 3355443},
#line 299 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1557, 1710618},
    {-1}, {-1}, {-1},
#line 441 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1561, 15761536},
    {-1}, {-1},
#line 96 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1564, 3100495},
    {-1},
#line 611 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1566, 16767673},
    {-1},
#line 224 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1568, 6710886},
#line 213 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1569, 5066061},
    {-1}, {-1},
#line 202 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1572, 3355443},
#line 190 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1573, 1710618},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 95 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1580, 3100495},
    {-1}, {-1},
#line 432 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1583, 8190976},
    {-1},
#line 640 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1585, 12357519},
    {-1}, {-1},
#line 501 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1588, 16777184},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 47 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1603, 6266528},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 523 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1609, 3978097},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 29 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1616, 16772045},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 81 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1634, 35723},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 530 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1642, 12211667},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 452 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1678, 8679679},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 90 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1686, 10040012},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1},
#line 628 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1697, 11591910},
    {-1},
#line 534 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1699, 8009611},
    {-1},
#line 533 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1701, 11817677},
    {-1}, {-1}, {-1},
#line 522 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1705, 9662683},
    {-1},
#line 532 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1707, 13721582},
    {-1},
#line 531 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1709, 14706431},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 402 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1725, 8620931},
    {-1},
#line 401 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1727, 12701121},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 400 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1733, 14741216},
#line 546 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1734, 1644912},
#line 399 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1735, 15794160},
    {-1}, {-1}, {-1},
#line 454 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1739, 7833753},
    {-1}, {-1},
#line 149 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1742, 9112144},
    {-1},
#line 148 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1744, 13439094},
    {-1}, {-1},
#line 387 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1747, 1513239},
    {-1}, {-1},
#line 147 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1750, 15602313},
    {-1},
#line 146 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1752, 16716947},
    {-1},
#line 442 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1754, 14745599},
#line 453 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1755, 7833753},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 278 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1763, 1513239},
    {-1},
#line 376 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1765, 1315860},
    {-1},
#line 455 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1767, 11584734},
    {-1}, {-1}, {-1},
#line 365 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1771, 1184274},
    {-1},
#line 97 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1773, 52945},
    {-1}, {-1}, {-1},
#line 548 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1777, 16121850},
    {-1}, {-1}, {-1},
#line 267 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1781, 1315860},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 256 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1787, 1184274},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 342 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1804, 8224125},
#line 331 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1805, 6513507},
    {-1}, {-1},
#line 320 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1808, 4868682},
#line 309 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1809, 3158064},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 555 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1817, 16770229},
    {-1}, {-1},
#line 233 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1820, 8224125},
#line 222 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1821, 6513507},
#line 341 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1822, 8026746},
#line 330 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1823, 6381921},
#line 211 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1824, 4868682},
#line 200 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1825, 3158064},
#line 319 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1826, 4671303},
#line 308 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1827, 3026478},
#line 340 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1828, 7895160},
#line 329 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1829, 6184542},
#line 473 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1830, 16448210},
    {-1},
#line 318 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1832, 4539717},
#line 307 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1833, 2829099},
    {-1}, {-1}, {-1}, {-1},
#line 232 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1838, 8026746},
#line 221 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1839, 6381921},
    {-1}, {-1},
#line 210 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1842, 4671303},
#line 199 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1843, 3026478},
#line 231 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1844, 7895160},
#line 220 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1845, 6184542},
    {-1}, {-1},
#line 209 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1848, 4539717},
#line 198 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1849, 2829099},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 420 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1858, 15787660},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 6 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1866, 16444375},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 735 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1872, 13639824},
#line 547 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1873, 16121850},
    {-1}, {-1},
#line 121 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1876, 10040012},
#line 125 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1877, 6824587},
#line 124 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1878, 10105549},
    {-1}, {-1},
#line 123 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1881, 11680494},
#line 122 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1882, 12533503},
    {-1},
#line 563 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1884, 128},
#line 354 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1885, 986895},
    {-1}, {-1},
#line 750 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1888, 10145074},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1},
#line 245 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1901, 986895},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 481 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1908, 9133925},
#line 480 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1909, 13470869},
    {-1}, {-1},
#line 479 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1912, 15639213},
#line 478 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1913, 16756409},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 10 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1923, 9143160},
    {-1},
#line 9 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1925, 13484208},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 8 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1931, 15654860},
    {-1},
#line 7 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1933, 16773083},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 339 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1942, 7697781},
#line 328 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1943, 6052956},
    {-1}, {-1},
#line 317 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1946, 4342338},
#line 306 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1947, 2697513},
#line 591 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1948, 11529966},
    {-1}, {-1},
#line 343 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1951, 855309},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 230 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1958, 7697781},
#line 219 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1959, 6052956},
#line 749 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1960, 16776960},
    {-1},
#line 208 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1962, 4342338},
#line 197 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1963, 2697513},
#line 524 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1964, 8087790},
    {-1}, {-1},
#line 234 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1967, 855309},
#line 431 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1968, 9143174},
    {-1},
#line 430 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1970, 13484485},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 429 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1976, 15655141},
    {-1},
#line 428 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1978, 16773365},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 170 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1985, 16775920},
    {-1},
#line 521 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1987, 12211667},
    {-1},
#line 543 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1989, 4772300},
    {-1},
#line 528 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1991, 6737322},
#line 451 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1992, 8900346},
#line 408 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1993, 9124450},
    {-1},
#line 407 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str1995, 13459600},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 406 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2001, 15624871},
    {-1},
#line 405 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2003, 16740020},
    {-1}, {-1}, {-1}, {-1},
#line 338 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2008, 7566195},
#line 327 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2009, 5855577},
    {-1}, {-1},
#line 316 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2012, 4210752},
#line 305 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2013, 2500134},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 444 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2022, 16448210},
    {-1},
#line 229 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2024, 7566195},
#line 218 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2025, 5855577},
    {-1}, {-1},
#line 207 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2028, 4210752},
#line 196 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2029, 2500134},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1},
#line 5 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2067, 16444375},
#line 144 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2068, 49151},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 141 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2093, 9699539},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1},
#line 69 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2107, 6591981},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1},
#line 171 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2119, 16775920},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1},
#line 525 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2130, 64154},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1},
#line 74 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2141, 9144440},
    {-1},
#line 73 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2143, 13486257},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 72 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2149, 15657165},
    {-1},
#line 71 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2151, 16775388},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 169 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2161, 9116186},
#line 168 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2162, 13444646},
    {-1}, {-1},
#line 167 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2165, 15608876},
#line 166 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2166, 16724016},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 68 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2176, 6591981},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 36 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2185, 9055202},
    {-1}, {-1},
#line 545 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2188, 1644912},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1},
#line 28 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2218, 16772045},
    {-1},
#line 111 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2220, 5597999},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 427 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2230, 16773365},
    {-1},
#line 115 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2232, 7244605},
    {-1},
#line 114 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2234, 10669402},
    {-1},
#line 448 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2236, 16758465},
    {-1}, {-1}, {-1},
#line 113 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2240, 12381800},
    {-1},
#line 112 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2242, 13303664},
    {-1}, {-1}, {-1}, {-1},
#line 300 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2247, 16777215},
#line 604 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2248, 14381203},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1},
#line 145 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2260, 16716947},
    {-1}, {-1},
#line 191 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2263, 16777215},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 747 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2279, 16119285},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 608 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2305, 9127773},
#line 176 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2306, 16316671},
#line 607 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2307, 13461641},
    {-1}, {-1}, {-1},
#line 388 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2311, 15066597},
    {-1},
#line 606 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2313, 15628703},
    {-1},
#line 605 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2315, 16745131},
    {-1}, {-1}, {-1}, {-1},
#line 377 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2320, 13421772},
    {-1}, {-1},
#line 366 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2323, 11776947},
    {-1}, {-1}, {-1},
#line 279 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2327, 15066597},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 268 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2336, 13421772},
    {-1}, {-1},
#line 257 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2339, 11776947},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 435 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2347, 16775885},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1},
#line 439 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2359, 9144688},
    {-1},
#line 438 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2361, 13486501},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 437 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2367, 15657407},
    {-1},
#line 436 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2369, 16775885},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1},
#line 355 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2380, 10066329},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 398 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2389, 15794160},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 246 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2396, 10066329},
    {-1},
#line 526 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2398, 4772300},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 344 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2413, 8355711},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 98 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2422, 9699539},
    {-1}, {-1}, {-1}, {-1},
#line 519 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2427, 6737322},
    {-1},
#line 235 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2429, 8355711},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 609 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2464, 16773077},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 477 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2482, 16758465},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 175 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2500, 16316671},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1},
#line 404 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2511, 16738740},
    {-1}, {-1},
#line 31 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2514, 9055202},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1},
#line 748 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2525, 16119285},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 290 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2544, 11403055},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 88 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2562, 5597999},
#line 397 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2563, 16579836},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 386 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2572, 14935011},
    {-1}, {-1},
#line 375 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2575, 13224393},
    {-1}, {-1}, {-1},
#line 288 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2579, 16579836},
    {-1},
#line 396 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2581, 16448250},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 395 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2587, 16250871},
#line 277 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2588, 14935011},
    {-1},
#line 385 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2590, 14737632},
#line 266 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2591, 13224393},
    {-1},
#line 374 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2593, 13092807},
    {-1}, {-1},
#line 384 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2596, 14606046},
#line 287 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2597, 16448250},
    {-1},
#line 373 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2599, 12895428},
    {-1}, {-1}, {-1},
#line 286 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2603, 16250871},
    {-1}, {-1},
#line 276 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2606, 14737632},
    {-1}, {-1},
#line 265 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2609, 13092807},
    {-1}, {-1},
#line 275 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2612, 14606046},
    {-1}, {-1},
#line 264 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2615, 12895428},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 364 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2632, 11579568},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1},
#line 143 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2645, 16716947},
    {-1}, {-1},
#line 255 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2648, 11579568},
    {-1},
#line 363 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2650, 11382189},
    {-1}, {-1}, {-1},
#line 610 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2654, 16773077},
    {-1},
#line 362 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2656, 11250603},
    {-1}, {-1},
#line 70 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2659, 16775388},
    {-1}, {-1}, {-1}, {-1},
#line 456 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2664, 16777184},
#line 353 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2665, 9868950},
#line 254 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2666, 11382189},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 253 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2672, 11250603},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 244 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2681, 9868950},
    {-1},
#line 352 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2683, 9737364},
#line 426 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2684, 16773365},
    {-1}, {-1}, {-1}, {-1},
#line 351 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2689, 9539985},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 243 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2699, 9737364},
    {-1},
#line 394 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2701, 16119285},
    {-1}, {-1}, {-1},
#line 242 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2705, 9539985},
    {-1}, {-1}, {-1}, {-1},
#line 383 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2710, 14408667},
    {-1}, {-1},
#line 372 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2713, 12763842},
#line 403 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2714, 16738740},
#line 434 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2715, 16775885},
    {-1},
#line 285 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2717, 16119285},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 274 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2726, 14408667},
    {-1}, {-1},
#line 263 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2729, 12763842},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 165 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2735, 11674146},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1},
#line 393 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2767, 15921906},
    {-1}, {-1},
#line 361 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2770, 11053224},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 382 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2776, 14277081},
    {-1}, {-1},
#line 371 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2779, 12566463},
    {-1}, {-1}, {-1},
#line 284 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2783, 15921906},
    {-1}, {-1},
#line 252 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2786, 11053224},
    {-1}, {-1}, {-1}, {-1},
#line 86 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2791, 12433259},
#line 273 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2792, 14277081},
    {-1}, {-1},
#line 262 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2795, 12566463},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 350 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2803, 9408399},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 241 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2819, 9408399},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 360 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2836, 10921638},
    {-1}, {-1},
#line 544 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2839, 13047173},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1},
#line 251 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2852, 10921638},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 349 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2869, 9211020},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
#line 556 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2879, 16768685},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 240 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2885, 9211020},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 109 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str2981, 12433259},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1},
#line 557 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str3013, 16768685},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 592 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str3019, 14381203},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 561 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str3070, 9140574},
    {-1},
#line 560 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str3072, 13480843},
    {-1}, {-1}, {-1}, {-1}, {-1},
#line 559 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str3078, 15650721},
    {-1},
#line 558 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str3080, 16768685},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1}, {-1},
    {-1},
#line 527 "/dev/stdin"
    {(int)(size_t)&((struct stringpool_t *)0)->stringpool_str3478, 13047173}
  };
#if (defined __GNUC__ && __GNUC__ + (__GNUC_MINOR__ >= 6) > 4) || (defined __clang__ && __clang_major__ >= 3)
#pragma GCC diagnostic pop
#endif

const struct Keyword *
in_color_name_set (register const char *str, register size_t len)
{
  if (len <= MAX_WORD_LENGTH && len >= MIN_WORD_LENGTH)
    {
      register unsigned int key = color_name_hash (str, len);

      if (key <= MAX_HASH_VALUE)
        {
          register int o = color_names[key].name;
          if (o >= 0)
            {
              register const char *s = o + stringpool;

              if (*str == *s && !strncmp (str + 1, s + 1, len - 1) && s[len] == '\0')
                return &color_names[key];
            }
        }
    }
  return (struct Keyword *) 0;
}
#line 756 "/dev/stdin"

