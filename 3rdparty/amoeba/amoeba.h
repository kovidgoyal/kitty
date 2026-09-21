#ifndef amoeba_h
#define amoeba_h

#ifndef AM_NS_BEGIN
# ifdef __cplusplus
#   define AM_NS_BEGIN extern "C" {
#   define AM_NS_END   }
# else
#   define AM_NS_BEGIN
#   define AM_NS_END
# endif
#endif /* AM_NS_BEGIN */

#ifndef AM_STATIC
# ifdef __GNUC__
#   define AM_STATIC static __attribute((unused))
# else
#   define AM_STATIC static
# endif
#endif

#ifdef AM_STATIC_API
# ifndef AM_IMPLEMENTATION
#  define AM_IMPLEMENTATION
# endif
# define AM_API AM_STATIC
#endif

#if !defined(AM_API) && defined(_WIN32)
# ifdef AM_IMPLEMENTATION
#  define AM_API __declspec(dllexport)
# else
#  define AM_API __declspec(dllimport)
# endif
#endif

#ifndef AM_API
# define AM_API extern
#endif

#define AM_OK           (0)
#define AM_FAILED       (-1)
#define AM_UNSATISFIED  (-2)
#define AM_UNBOUND      (-3)

#define AM_LESSEQUAL    (1)
#define AM_EQUAL        (2)
#define AM_GREATEQUAL   (3)

#define AM_REQUIRED     ((am_Num)INFINITY)
#define AM_STRONG       ((am_Num)1000000)
#define AM_MEDIUM       ((am_Num)1000)
#define AM_WEAK         ((am_Num)1)

#include <stddef.h>
#include <math.h>

AM_NS_BEGIN


#ifdef AM_NUM
typedef AM_NUM am_Num;
#elif defined(AM_USE_DOUBLE)
typedef double am_Num;
#else
typedef float  am_Num;
#endif

typedef struct am_Solver     am_Solver;
typedef struct am_Constraint am_Constraint;

typedef unsigned am_Id;

typedef enum am_AllocType {
    am_AllocSolver = 1,
    am_AllocConstraint,
    am_AllocSuggest,
    am_AllocHash,
    am_AllocDump
} am_AllocType;

typedef void *am_Allocf (void **pud, void *ptr,
        size_t nsize, size_t osize, am_AllocType ty);

AM_API am_Solver *am_newsolver   (am_Allocf *allocf, void *ud);
AM_API void       am_resetsolver (am_Solver *S);
AM_API void       am_delsolver   (am_Solver *S);

AM_API void am_updatevars (am_Solver *S);
AM_API void am_autoupdate (am_Solver *S, int auto_update);

AM_API int  am_add    (am_Constraint *cons);
AM_API void am_remove (am_Constraint *cons);

AM_API void am_clearedits (am_Solver *S);
AM_API int  am_hasedit (am_Solver *S, am_Id var);
AM_API int  am_addedit (am_Solver *S, am_Id var, am_Num strength);
AM_API void am_suggest (am_Solver *S, am_Id var, am_Num value);
AM_API void am_deledit (am_Solver *S, am_Id var);

AM_API am_Id am_newvariable (am_Solver *S, am_Num *pvalue);
AM_API void  am_delvariable (am_Solver *S, am_Id var);

AM_API am_Num *am_varvalue (am_Solver *S, am_Id var, am_Num *newvalue);

AM_API int am_refcount      (am_Solver *S, am_Id var);
AM_API int am_hasconstraint (am_Constraint *cons);

AM_API am_Constraint *am_newconstraint   (am_Solver *S, am_Num strength);
AM_API am_Constraint *am_cloneconstraint (am_Constraint *other, am_Num strength);

AM_API void am_resetconstraint (am_Constraint *cons);
AM_API void am_delconstraint   (am_Constraint *cons);

AM_API int am_addterm     (am_Constraint *cons, am_Id var, am_Num multiplier);
AM_API int am_setrelation (am_Constraint *cons, int relation);
AM_API int am_addconstant (am_Constraint *cons, am_Num constant);
AM_API int am_setstrength (am_Constraint *cons, am_Num strength);

AM_API int am_mergeconstraint (am_Constraint *cons, const am_Constraint *other, am_Num multiplier);

/* dump & load */

typedef struct am_Dumper am_Dumper;
typedef struct am_Loader am_Loader;

AM_API int am_dump (am_Solver *S, am_Dumper *dumper);
AM_API int am_load (am_Solver *S, am_Loader *loader);

struct am_Dumper {
    const char *(*var_name)  (am_Dumper *D, unsigned idx, am_Id var, am_Num *value);
    const char *(*cons_name) (am_Dumper *D, unsigned idx, am_Constraint *cons);

    int (*writer) (am_Dumper *D, const void *buf, size_t len);
};

struct am_Loader {
    am_Num *(*load_var)  (am_Loader *L, const char *name, unsigned idx, am_Id var);
    void    (*load_cons) (am_Loader *L, const char *name, unsigned idx, am_Constraint *cons);

    const char *(*reader) (am_Loader *L, size_t *plen);
};


AM_NS_END

#endif /* amoeba_h */

#if defined(AM_IMPLEMENTATION) && !defined(am_implemented)
#define am_implemented

#include <assert.h>
#include <float.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>

#define AM_EXTERNAL     (0)
#define AM_SLACK        (1)
#define AM_ERROR        (2)
#define AM_DUMMY        (3)

#define am_isexternal(key)   ((key).type == AM_EXTERNAL)
#define am_isslack(key)      ((key).type == AM_SLACK)
#define am_iserror(key)      ((key).type == AM_ERROR)
#define am_isdummy(key)      ((key).type == AM_DUMMY)
#define am_ispivotable(key)  (am_isslack(key) || am_iserror(key))

#define am_alloc(T,S,ty) ((T*)(S)->allocf((void**)(S),NULL,sizeof(T),0,(ty)))
#define am_free(S,p,ty)  ((S)->allocf((void**)(S),(p),0,sizeof(*(p)),(ty)))

#define AM_MIN_HASHSIZE  8
#define AM_POOL_SIZE     4096
#define AM_UNSIGNED_BITS (sizeof(unsigned)*CHAR_BIT)

#ifdef AM_USE_DOUBLE
# define AM_NUM_MAX DBL_MAX
# define AM_NUM_EPS 1e-6
#else
# define AM_NUM_MAX FLT_MAX
# define AM_NUM_EPS 1e-4
#endif

#ifndef AM_DEBUG
# ifdef __GNUC__
#   pragma GCC diagnostic ignored "-Wvariadic-macros"
# endif
# define AM_DEBUG(...) ((void)0)
#endif /* AM_DEBUG */

#define amC(cond) do { if (!(cond)) return \
    AM_DEBUG(__FILE__ ":%d: " #cond "\n", __LINE__), AM_FAILED; } while (0)
#define amE(cond) amC((cond) == AM_OK)

AM_NS_BEGIN


typedef unsigned am_Size;

typedef struct am_Symbol {
    unsigned id   : AM_UNSIGNED_BITS - 2;
    unsigned type : 2;
} am_Symbol;

typedef struct am_MemPool {
    size_t size;
    void  *freed;
    void  *pages;
} am_MemPool;

typedef struct am_Key {
    int       next;
    am_Symbol sym;
} am_Key;

typedef struct am_Arena {
    size_t size;
    void  *buf;
} am_Arena;

typedef struct am_Table {
    am_Size size;
    am_Size count;
    am_Size value_size : AM_UNSIGNED_BITS - 1;
    am_Size arena      : 1;
    am_Size last_free;
    am_Key *keys;
    void   *vals;
} am_Table;

typedef struct am_Iterator {
    const am_Table *t;
    am_Symbol key;
    am_Size   offset;
} am_Iterator;

typedef struct am_Row {
    am_Symbol infeasible_next;
    am_Num    constant;
    am_Table  terms;
} am_Row;

typedef struct am_Var {
    am_Symbol next;
    unsigned  refcount;
    am_Num   *pvalue;
} am_Var;

struct am_Constraint {
    void      *ud;
    am_Row     expression;
    am_Symbol  sym; /* AM_EXTERNAL for pool cons, AM_DUMMY for suggest */
    am_Symbol  marker;
    am_Symbol  other;
    unsigned   marker_id;
    unsigned   other_id : AM_UNSIGNED_BITS - 2;
    unsigned   relation : 2;
    am_Num     strength;
    am_Solver *S;
};

typedef struct am_Suggest {
    am_Size       age;
    am_Num        edit_value;
    am_Constraint constraint;
    am_Table      dirtyset;
} am_Suggest;

struct am_Solver {
    void      *ud; /* must be the first for `am_default_allocf` */
    am_Allocf *allocf;
    am_Row     objective;
    am_Table   vars;            /* symbol -> am_Var */
    am_Table   constraints;     /* symbol -> am_Constraint* */
    am_Table   suggests;        /* symbol -> am_Suggest* */
    am_Table   rows;            /* symbol -> am_Row */
    am_Arena   arena;
    am_Size    auto_update;
    am_Size    age; /* counts of rows changed */
    am_Size    current_id;
    am_Size    current_cons;
    am_Symbol  infeasible_rows;
    am_Symbol  dirty_vars;
    am_MemPool conspool;
};

/* utils */

static int am_approx(am_Num a, am_Num b)
{ return a > b ? a - b < AM_NUM_EPS : b - a < AM_NUM_EPS; }

static int am_nearzero(am_Num a) { return am_approx(a, 0.f); }
static int am_negative(am_Num a) { return !am_nearzero(a) && a < 0.f; }
static am_Symbol am_null(void) { am_Symbol null = { 0, 0 }; return null; }

static void am_poolfree(am_MemPool *pool, void *obj)
{ *(void**)obj = pool->freed, pool->freed = obj; }

static void am_freearena(am_Solver *S, am_Arena *a) {
    if (!a->buf) return;
    S->allocf(&S->ud, a->buf, 0, a->size, am_AllocDump);
    a->buf = NULL, a->size = 0;
}

static void am_allocarena(am_Solver *S, am_Arena *a, size_t size) {
    assert(a->buf == NULL);
    a->buf = S->allocf(&S->ud, NULL, size, 0, am_AllocDump);
    if (a->buf) a->size = size;
}

static void am_initpool(am_MemPool *pool, size_t size) {
    pool->size  = size;
    pool->freed = pool->pages = NULL;
    assert(size > sizeof(void*) && size < AM_POOL_SIZE/4);
}

static void am_freepool(am_MemPool *pool) {
    const size_t offset = AM_POOL_SIZE - sizeof(void*);
    while (pool->pages != NULL) {
        void *next = *(void**)((char*)pool->pages + offset);
        free(pool->pages);
        pool->pages = next;
    }
}

static void *am_poolalloc(am_MemPool *pool) {
    void *obj = pool->freed;
    if (obj == NULL) {
        const size_t offset = AM_POOL_SIZE - sizeof(void*);
        void *end, *ptr = malloc(AM_POOL_SIZE);
        if (ptr == NULL) abort();
        *(void**)((char*)ptr + offset) = pool->pages;
        pool->pages = ptr;
        end = (char*)ptr + (offset/pool->size-1)*pool->size;
        while (end != ptr) {
            *(void**)end = pool->freed;
            pool->freed = (void**)end;
            end = (char*)end - pool->size;
        }
        return end;
    }
    pool->freed = *(void**)obj;
    return obj;
}

static void *am_default_allocf(void **pud, void *ptr, size_t nsize, size_t osize, am_AllocType ty) {
    void *newptr;
    (void)osize;
    if (ty == am_AllocConstraint) {
        am_Solver *S = (am_Solver*)pud;
        if (nsize) return am_poolalloc(&S->conspool);
        return am_poolfree(&S->conspool, ptr), (void*)NULL;
    }
    if (nsize == 0) return free(ptr), (void*)NULL;
    if ((newptr = realloc(ptr, nsize)) == NULL) abort();
    return newptr;
}

static am_Symbol am_newsymbol(am_Solver *S, int type) {
    am_Symbol sym;
    unsigned id = ++S->current_id;
    if (id > 0x3FFFFFFF) abort(); /* id runs out */
    assert(type >= AM_EXTERNAL && type <= AM_DUMMY);
    sym.id   = id;
    sym.type = type;
    return sym;
}

/* hash table */

#define amH_val(t,i)  ((char*)(t)->vals+(i)*(t)->value_size)
#define am_val(T,it)  ((T*)amH_val((it).t,(it).offset-1))

static am_Iterator am_itertable(const am_Table *t)
{ am_Iterator it; it.t = t, it.key = am_null(), it.offset = 0; return it; }

static void am_inittable(am_Table *t, size_t value_size)
{ memset(t, 0, sizeof(*t)), t->value_size = (am_Size)value_size; }

static void am_resettable(am_Table *t)
{ t->last_free = t->count = 0; memset(t->keys, 0, t->size * sizeof(am_Key)); }

static am_Size am_calcsize(am_Size request)
{ am_Size s = AM_MIN_HASHSIZE; while (s < request) s <<= 1; return s; }

static int am_nextentry(am_Iterator *it) {
    am_Size cur = it->offset, size = it->t->size;
    am_Symbol key;
    while (cur < size && (key = it->t->keys[cur].sym).id == 0) cur++;
    if (cur == size) return it->key = am_null(), it->offset = 0;
    return it->key = key, it->offset = cur + 1;
}

static void am_freetable(const am_Solver *S, am_Table *t) {
    size_t hsize = t->size * (sizeof(am_Key) + t->value_size);
    if (hsize == 0) return;
    if (!t->arena) S->allocf((void**)S, t->keys, 0, hsize, am_AllocHash);
    am_inittable(t, t->value_size);
}

static const void *am_gettable(const am_Table *t, unsigned key) {
    am_Size cur;
    if (t->size == 0) return NULL;
    cur = key & (t->size - 1);
    for (; t->keys[cur].sym.id != key; cur += t->keys[cur].next)
        if (t->keys[cur].next == 0) return NULL;
    return amH_val(t, cur);
}

static int amH_alloc(am_Table *t, const am_Solver *S, size_t request, size_t vsize, void **arena) {
    size_t size, hsize;
    am_Key *keys;
    amC(request <= (~(am_Size)0 >> 1));
    size = am_calcsize((am_Size)request);
    hsize = size * (sizeof(am_Key) + vsize);
    if (arena) keys = (am_Key*)*arena, *arena = (char*)*arena + hsize;
    else keys = (am_Key*)S->allocf((void**)S, NULL, hsize, 0, am_AllocHash);
    amC(keys != NULL);
    t->size = (am_Size)size;
    t->value_size = vsize;
    t->arena = (arena != NULL);
    t->keys = keys;
    t->vals = keys + t->size;
    return am_resettable(t), AM_OK;
}

static void *amH_rawset(am_Table *t, am_Symbol key) {
    int mp = key.id & (t->size - 1);
    am_Key *ks = t->keys;
    if (ks[mp].sym.id) {
        int f = t->last_free, othern;
        while (f < (int)t->size && (ks[f].sym.id || ks[f].next))
            f += 1;
        if (f == (int)t->size) return NULL;
        t->last_free = f + 1;
        if ((othern = ks[mp].sym.id & (t->size - 1)) == mp) {
            if (ks[mp].next) ks[f].next = (mp + ks[mp].next) - f;
            ks[mp].next = (f - mp), mp = f;
        } else {
            assert(ks[othern].next != 0);
            while (othern + ks[othern].next != mp)
                othern += ks[othern].next;
            ks[othern].next = (f - othern);
            ks[f] = ks[mp], memcpy(amH_val(t,f), amH_val(t,mp), t->value_size);
            if (ks[mp].next) ks[f].next += (mp - f), ks[mp].next = 0;
        }
    }
    return ks[mp].sym = key, amH_val(t, mp);
}

static int amH_resize(const am_Solver *S, am_Table *t, size_t request, void **arena) {
    am_Table nt;
    am_Size i;
    amE(amH_alloc(&nt, S, request, t->value_size, arena));
    for (i = 0; i < t->size; ++i) {
        void *value;
        if (!t->keys[i].sym.id) continue;
        value = amH_rawset(&nt, t->keys[i].sym);
        assert(value != NULL), memcpy(value, amH_val(t, i), t->value_size);
    }
    nt.count = t->count;
    if (!t->arena) am_freetable(S, t);
    return (*t = nt), AM_OK;
}

static int am_growtable(const am_Solver *S, am_Table *t, size_t grow, void **a)
{ return (grow += t->count)*2 < t->size ? AM_OK : amH_resize(S, t, grow, a); }

static void *am_settable(const am_Solver *S, am_Table *t, am_Symbol key) {
    void *value;
    assert(key.id != 0 && am_gettable(t, key.id) == NULL);
    if (!t->size && amH_resize(S, t, 0, NULL) != AM_OK) return NULL;
    if ((value = amH_rawset(t, key)) == NULL) {
        if (amH_resize(S, t, t->count*2, NULL) != AM_OK) return NULL;
        value = amH_rawset(t, key); /* retry and must success */
    }
    return t->count += 1, assert(value != NULL), value;
}

static void am_deltable(am_Table *t, const void *value) {
    size_t offset = ((char*)value - (char*)t->vals)/t->value_size;
    t->count -= 1, t->keys[offset].sym = am_null();
}

/* expression (row) */

static void am_freerow(am_Solver *S, am_Row *row)
{ am_freetable(S, &row->terms); }

static void am_resetrow(am_Row *row)
{ row->constant = 0.f; am_resettable(&row->terms); }

static void am_initrow(am_Row *row) {
    row->infeasible_next = am_null(), row->constant = 0.f;
    am_inittable(&row->terms, sizeof(am_Num));
}

static void am_multiply(am_Row *row, am_Num multiplier) {
    am_Iterator it = am_itertable(&row->terms);
    row->constant *= multiplier;
    while (am_nextentry(&it))
        *am_val(am_Num,it) *= multiplier;
}

static void am_addvar(am_Solver *S, am_Row *row, am_Symbol sym, am_Num value) {
    am_Num *term;
    if (sym.id == 0 || am_nearzero(value)) return;
    term = (am_Num*)am_gettable(&row->terms, sym.id);
    if (term == NULL) {
        term = (am_Num*)am_settable(S, &row->terms, sym);
        assert(term != NULL);
        *term = value;
    } else if (am_nearzero(*term += value))
        am_deltable(&row->terms, term);
}

static void am_addrow(am_Solver *S, am_Row *row, const am_Row *other, am_Num multiplier) {
    am_Iterator it = am_itertable(&other->terms);
    row->constant += other->constant*multiplier;
    while (am_nextentry(&it))
        am_addvar(S, row, it.key, *am_val(am_Num,it)*multiplier);
}

/* variables & constraints */

AM_API int am_hasconstraint(am_Constraint *cons)
{ return cons != NULL && cons->marker.id != 0; }

AM_API void am_autoupdate(am_Solver *S, int auto_update)
{ S->auto_update = auto_update; }

static am_Var *am_id2var(am_Solver *S, am_Id var)
{ return S ? (am_Var*)am_gettable(&S->vars, var) : NULL; }

AM_API am_Id am_newvariable(am_Solver *S, am_Num *pvalue) {
    am_Symbol sym;
    am_Var *ve;
    if (S == NULL || pvalue == NULL) return 0;
    sym = am_newsymbol(S, AM_EXTERNAL);
    ve = (am_Var*)am_settable(S, &S->vars, sym);
    if (ve == NULL) return 0;
    memset(ve, 0, sizeof(*ve));
    ve->pvalue   = pvalue;
    ve->refcount = 1;
    return sym.id;
}

AM_API void am_delvariable(am_Solver *S, am_Id var) {
    am_Var *ve = am_id2var(S, var);
    if (ve && --ve->refcount == 0) {
        assert(!am_isdummy(ve->next));
        am_deledit(S, var);
        am_deltable(&S->vars, ve);
    }
}

AM_API int am_refcount(am_Solver *S, am_Id var) {
    am_Var *ve = am_id2var(S, var);
    return ve ? ve->refcount : 0;
}

AM_API am_Num *am_varvalue(am_Solver *S, am_Id var, am_Num *newvalue) {
    am_Var *ve = am_id2var(S, var);
    am_Num *pvalue = ve ? ve->pvalue : NULL;
    if (ve && newvalue) ve->pvalue = newvalue;
    return pvalue;
}

AM_API void am_updatevars(am_Solver *S) {
    while (S->dirty_vars.id != 0) {
        am_Symbol var = S->dirty_vars;
        am_Var *ve = (am_Var*)am_gettable(&S->vars, var.id);
        assert(ve != NULL);
        S->dirty_vars = ve->next;
        ve->next = am_null();
        if (ve->refcount == 1) {
            am_deledit(S, var.id);
            am_deltable(&S->vars, ve);
        } else {
            am_Row *row = (am_Row*)am_gettable(&S->rows, var.id);
            *ve->pvalue = row ? row->constant : 0.f;
            ve->refcount -= 1;
        }
    }
}

static int am_initconstraint(am_Solver *S, am_Symbol sym, am_Num strength, am_Constraint *cons) {
    am_Constraint **ce = (am_Constraint**)am_settable(S, &S->constraints, sym);
    amC(ce != NULL);
    *ce = cons;
    memset(cons, 0, sizeof(*cons));
    cons->S        = S;
    cons->sym      = sym;
    cons->strength = am_nearzero(strength) ? AM_REQUIRED : strength;
    am_initrow(&(*ce)->expression);
    return AM_OK;
}

AM_API am_Constraint *am_newconstraint(am_Solver *S, am_Num strength) {
    am_Symbol sym = {0, AM_EXTERNAL}; /* AM_EXTERNAL for pool cons */
    am_Constraint *cons;
    int ret;
    if (S == NULL || am_negative(strength)) return NULL;
    cons = am_alloc(am_Constraint, S, am_AllocConstraint);
    if (cons == NULL) return NULL;
    sym.id = ++S->current_cons;
    ret = am_initconstraint(S, sym, strength, cons);
    if (ret != AM_OK) am_free(S, cons, am_AllocConstraint), cons = NULL;
    return cons;
}

AM_API void am_delconstraint(am_Constraint *cons) {
    am_Solver *S = cons ? cons->S : NULL;
    am_Iterator it;
    am_Constraint **ce;
    if (S == NULL) return;
    am_remove(cons);
    ce = (am_Constraint**)am_gettable(&S->constraints, cons->sym.id);
    assert(ce != NULL && *ce == cons);
    am_deltable(&S->constraints, ce);
    it = am_itertable(&cons->expression.terms);
    while (am_nextentry(&it))
        am_delvariable(cons->S, it.key.id);
    am_freerow(S, &cons->expression);
    if (am_isexternal(cons->sym)) am_free(S, cons, am_AllocConstraint);
}

AM_API am_Constraint *am_cloneconstraint(am_Constraint *other, am_Num strength) {
    am_Constraint *cons;
    if (other == NULL) return NULL;
    cons = am_newconstraint(other->S,
            am_nearzero(strength) ? other->strength : strength);
    am_mergeconstraint(cons, other, 1.0f);
    cons->relation = other->relation;
    return cons;
}

AM_API int am_mergeconstraint(am_Constraint *cons, const am_Constraint *other, am_Num multiplier) {
    am_Iterator it;
    amC(cons && other && cons->marker.id == 0 && cons->S == other->S);
    if (cons->relation == AM_GREATEQUAL) multiplier = -multiplier;
    cons->expression.constant += other->expression.constant*multiplier;
    it = am_itertable(&other->expression.terms);
    while (am_nextentry(&it)) {
        am_Var *ve = (am_Var*)am_gettable(&cons->S->vars, it.key.id);
        assert(ve != NULL);
        ve->refcount += 1;
        am_addvar(cons->S, &cons->expression, it.key,
                *am_val(am_Num,it)*multiplier);
    }
    return AM_OK;
}

AM_API void am_resetconstraint(am_Constraint *cons) {
    am_Iterator it;
    if (cons == NULL) return;
    am_remove(cons);
    cons->relation = 0;
    it = am_itertable(&cons->expression.terms);
    while (am_nextentry(&it))
        am_delvariable(cons->S, it.key.id);
    am_resetrow(&cons->expression);
}

AM_API int am_addterm(am_Constraint *cons, am_Id var, am_Num multiplier) {
    am_Symbol sym = {0, AM_EXTERNAL};
    am_Var *ve;
    amC(cons && var && cons->marker.id == 0);
    if (cons->relation == AM_GREATEQUAL) multiplier = -multiplier;
    amC(ve = (am_Var*)am_gettable(&cons->S->vars, var));
    am_addvar(cons->S, &cons->expression, (sym.id=var, sym), multiplier);
    return ve->refcount += 1, AM_OK;
}

AM_API int am_addconstant(am_Constraint *cons, am_Num constant) {
    amC(cons && cons->marker.id == 0);
    cons->expression.constant +=
        cons->relation == AM_GREATEQUAL ? -constant : constant;
    return AM_OK;
}

AM_API int am_setrelation(am_Constraint *cons, int relation) {
    assert(relation >= AM_LESSEQUAL && relation <= AM_GREATEQUAL);
    amC(cons && cons->marker.id == 0 && cons->relation == 0);
    if (relation != AM_GREATEQUAL) am_multiply(&cons->expression, -1.0f);
    cons->relation = relation;
    return AM_OK;
}

AM_API int am_hasedit(am_Solver *S, am_Id var) {
    if (S == NULL) return 0;
    return am_gettable(&S->suggests, var) != NULL;
}

static am_Suggest *am_newedit(am_Solver *S, am_Id var, am_Num strength) {
    am_Symbol sym = {0, AM_EXTERNAL};
    am_Suggest **s;
    am_Row *row;
    am_Var *ve;
    int ret;
    if (S == NULL || var == 0 || am_negative(strength)) return NULL;
    if ((ve = (am_Var*)am_gettable(&S->vars, var)) == NULL) return NULL;
    s = (am_Suggest**)am_settable(S, &S->suggests, (sym.id=var, sym));
    if (s == NULL) return NULL;
    *s = am_alloc(am_Suggest, S, am_AllocSuggest);
    if (*s == NULL) return am_deltable(&S->suggests, s), (am_Suggest*)NULL;
    memset(*s, 0, sizeof(**s));
    sym.id = ++S->current_cons, sym.type = AM_DUMMY; /* local cons */
    (*s)->edit_value = !am_isdummy(ve->next) ? *ve->pvalue :
        (row = (am_Row*)am_gettable(&S->rows, var)) ? row->constant : 0.f;
    am_initconstraint(S, sym, strength, &(*s)->constraint);
    am_setrelation(&(*s)->constraint, AM_EQUAL);
    am_addterm(&(*s)->constraint, var, 1.0f); /* var must have positive signture */
    am_addconstant(&(*s)->constraint, -(*s)->edit_value);
    ret = am_add(&(*s)->constraint);
    assert(ret == AM_OK), (void)ret;
    return *s;
}

AM_API int am_addedit(am_Solver *S, am_Id var, am_Num strength) {
    am_Suggest **s;
    amC(S && var);
    if (strength >= AM_STRONG) strength = AM_STRONG;
    s = (am_Suggest**)am_gettable(&S->suggests, var);
    if (s) return assert(*s), am_setstrength(&(*s)->constraint, strength);
    amC(am_newedit(S, var, strength));
    return AM_OK;
}

AM_API void am_deledit(am_Solver *S, am_Id var) {
    am_Suggest **ps, *s;
    if (S == NULL || var == 0) return;
    ps = (am_Suggest**)am_gettable(&S->suggests, var);
    if (ps == NULL) return;
    s = *ps, am_deltable(&S->suggests, ps);
    am_freetable(S, &s->dirtyset);
    am_delconstraint(&(s->constraint));
    am_free(S, s, am_AllocSuggest);
}

AM_API void am_clearedits(am_Solver *S) {
    am_Iterator it;
    if (S == NULL) return;
    it = am_itertable(&S->suggests);
    if (!S->auto_update) am_updatevars(S);
    while (am_nextentry(&it)) {
        am_Suggest *s = *am_val(am_Suggest*,it);
        am_freetable(S, &s->dirtyset);
        am_delconstraint(&s->constraint);
        am_free(S, s, am_AllocSuggest);
    }
    am_resettable(&S->suggests);
}

/* Cassowary algorithm */

static int am_takerow(am_Solver *S, am_Symbol sym, am_Row *dst) {
    am_Row *row = (am_Row*)am_gettable(&S->rows, sym.id);
    if (row == NULL) return AM_FAILED;
    am_deltable(&S->rows, row);
    dst->constant = row->constant;
    dst->terms    = row->terms;
    return AM_OK;
}

static void am_solvefor(am_Solver *S, am_Row *row, am_Symbol enter, am_Symbol leave) {
    am_Num *term = (am_Num*)am_gettable(&row->terms, enter.id);
    am_Num reciprocal = 1.0f / *term;
    assert(enter.id != leave.id && !am_nearzero(*term));
    am_deltable(&row->terms, term);
    if (!am_approx(reciprocal, -1.0f)) am_multiply(row, -reciprocal);
    if (leave.id != 0) am_addvar(S, row, leave, reciprocal);
}

static void am_eliminate(am_Solver *S, am_Row *dst, am_Symbol out, const am_Row *row) {
    am_Num *term = (am_Num*)am_gettable(&dst->terms, out.id);
    if (!term) return;
    am_deltable(&dst->terms, term);
    am_addrow(S, dst, row, *term);
}

static void am_markdirty(am_Solver *S, am_Symbol var) {
    am_Var *ve = (am_Var*)am_gettable(&S->vars, var.id);
    assert(ve != NULL);
    if (am_isdummy(ve->next)) return;
    ve->next.id = S->dirty_vars.id;
    ve->next.type = AM_DUMMY;
    S->dirty_vars = var;
    ve->refcount += 1;
}

static int am_infeasible(am_Solver *S, am_Symbol sym, am_Row *row) {
    if (am_isdummy(row->infeasible_next)) return 1;
    if (am_negative(row->constant)) {
        row->infeasible_next.id = S->infeasible_rows.id;
        row->infeasible_next.type = AM_DUMMY;
        return (S->infeasible_rows = sym), 1;
    }
    return 0;
}

static void am_substitute_rows(am_Solver *S, am_Symbol var, am_Row *expr) {
    am_Iterator it = am_itertable(&S->rows);
    while (am_nextentry(&it)) {
        am_Row *row = am_val(am_Row,it);
        am_eliminate(S, row, var, expr);
        if (am_isexternal(it.key))
            am_markdirty(S, it.key);
        else
            am_infeasible(S, it.key, row);
    }
    am_eliminate(S, &S->objective, var, expr);
}

static int am_putrow(am_Solver *S, am_Symbol sym, const am_Row *src) {
    am_Row *row;
    assert(am_gettable(&S->rows, sym.id) == NULL);
    row = (am_Row*)am_settable(S, &S->rows, sym);
    assert(row != NULL);
    row->infeasible_next = am_null();
    row->constant = src->constant;
    row->terms    = src->terms;
    return AM_OK;
}

static void am_optimize(am_Solver *S, am_Row *objective) {
    for (;;) {
        am_Symbol enter = am_null(), leave = am_null();
        am_Num r, min_ratio = AM_NUM_MAX, *term;
        am_Iterator it = am_itertable(&objective->terms);
        am_Row tmp;

        assert(S->infeasible_rows.id == 0);
        while (am_nextentry(&it))
            if (!am_isdummy(it.key) && am_negative(*am_val(am_Num, it))) break;
        if (it.key.id == 0) return;
        enter = it.key;

        it = am_itertable(&S->rows);
        while (am_nextentry(&it)) {
            am_Row *row = am_val(am_Row,it);
            if (am_isexternal(it.key)) continue;
            term = (am_Num*)am_gettable(&row->terms, enter.id);
            if (term == NULL || *term > 0.f) continue;
            r = -row->constant / *term;
            if (r < min_ratio || (am_approx(r, min_ratio)
                        && it.key.id < leave.id))
                min_ratio = r, leave = it.key;
        }
        assert(leave.id != 0);
        am_takerow(S, leave, &tmp);
        am_solvefor(S, &tmp, enter, leave);
        am_substitute_rows(S, enter, &tmp);
        if (objective != &S->objective)
            am_eliminate(S, objective, enter, &tmp);
        am_putrow(S, enter, &tmp);
    }
}

static void am_mergerow(am_Solver *S, am_Row *row, am_Symbol var, am_Num multiplier) {
    am_Row *oldrow = (am_Row*)am_gettable(&S->rows, var.id);
    if (oldrow) am_addrow(S, row, oldrow, multiplier);
    else        am_addvar(S, row, var, multiplier);
}

static am_Row am_makerow(am_Solver *S, am_Constraint *cons) {
    am_Iterator it = am_itertable(&cons->expression.terms);
    am_Row row;
    am_initrow(&row);
    row.constant = cons->expression.constant;
    while (am_nextentry(&it)) {
        am_markdirty(S, it.key);
        am_mergerow(S, &row, it.key, *am_val(am_Num,it));
    }
    if (cons->relation != AM_EQUAL) {
        cons->marker.id = cons->marker_id, cons->marker.type = AM_SLACK;
        am_addvar(S, &row, cons->marker, -1.0f);
        if (cons->strength < AM_REQUIRED) {
            cons->other.id = cons->other_id, cons->other.type = AM_ERROR;
            am_addvar(S, &row, cons->other, 1.0f);
            am_addvar(S, &S->objective, cons->other, cons->strength);
        }
    } else if (cons->strength >= AM_REQUIRED) {
        cons->marker.id = cons->marker_id, cons->marker.type = AM_DUMMY;
        am_addvar(S, &row, cons->marker, 1.0f);
    } else {
        cons->marker.id = cons->marker_id, cons->marker.type = AM_ERROR;
        cons->other.id = cons->other_id, cons->other.type = AM_ERROR;
        am_addvar(S, &row, cons->marker, -1.0f);
        am_addvar(S, &row, cons->other,   1.0f);
        am_addvar(S, &S->objective, cons->marker, cons->strength);
        am_addvar(S, &S->objective, cons->other,  cons->strength);
    }
    if (row.constant < 0.f) am_multiply(&row, -1.0f);
    return row;
}

static int am_add_with_artificial(am_Solver *S, am_Row *row, am_Constraint *cons) {
    am_Symbol a = am_newsymbol(S, AM_SLACK);
    am_Iterator it;
    am_Row tmp;
    am_Num *term;
    int ret;
    --S->current_id; /* artificial variable will be removed */
    am_initrow(&tmp);
    am_addrow(S, &tmp, row, 1.0f);
    am_putrow(S, a, row);
    am_optimize(S, &tmp);
    ret = am_nearzero(tmp.constant) ? AM_OK : AM_UNBOUND;
    am_freerow(S, &tmp);
    if (am_takerow(S, a, &tmp) == AM_OK) {
        am_Symbol enter = am_null();
        if (tmp.terms.count == 0) return am_freerow(S, &tmp), ret;
        it = am_itertable(&tmp.terms);
        while (am_nextentry(&it))
            if (am_ispivotable(it.key)) { enter = it.key; break; }
        if (enter.id == 0) return am_freerow(S, &tmp), AM_UNBOUND;
        am_solvefor(S, &tmp, enter, a);
        am_substitute_rows(S, enter, &tmp);
        am_putrow(S, enter, &tmp);
    }
    it = am_itertable(&S->rows);
    while (am_nextentry(&it)) {
        am_Row *row = am_val(am_Row,it);
        am_Num *term = (am_Num*)am_gettable(&row->terms, a.id);
        if (term) am_deltable(&row->terms, term);
    }
    term = (am_Num*)am_gettable(&S->objective.terms, a.id);
    if (term) am_deltable(&S->objective.terms, term);
    if (ret != AM_OK) am_remove(cons);
    return ret;
}

static int am_try_addrow(am_Solver *S, am_Row *row, am_Constraint *cons) {
    am_Symbol subject = am_null();
    am_Iterator it = am_itertable(&row->terms);
    while (am_nextentry(&it))
        if (am_isexternal(it.key)) { subject = it.key; break; }
    if (subject.id == 0 && am_ispivotable(cons->marker)) {
        am_Num *term = (am_Num*)am_gettable(&row->terms, cons->marker.id);
        if (*term < 0.f) subject = cons->marker;
    }
    if (subject.id == 0 && am_ispivotable(cons->other)) {
        am_Num *term = (am_Num*)am_gettable(&row->terms, cons->other.id);
        if (*term < 0.f) subject = cons->other;
    }
    if (subject.id == 0) {
        it = am_itertable(&row->terms);
        while (am_nextentry(&it))
            if (!am_isdummy(it.key)) break;
        if (it.offset == 0) {
            if (!am_nearzero(row->constant))
                return am_freerow(S, row), AM_UNSATISFIED;
            subject = cons->marker;
        }
    }
    if (subject.id == 0) return am_add_with_artificial(S, row, cons);
    am_solvefor(S, row, subject, am_null());
    am_substitute_rows(S, subject, row);
    am_putrow(S, subject, row);
    return AM_OK;
}

static void am_remove_errors(am_Solver *S, am_Constraint *cons) {
    if (am_iserror(cons->marker))
        am_mergerow(S, &S->objective, cons->marker, -cons->strength);
    if (am_iserror(cons->other))
        am_mergerow(S, &S->objective, cons->other, -cons->strength);
    if (S->objective.terms.count == 0)
        S->objective.constant = 0.f;
    cons->marker = cons->other = am_null();
}

AM_API int am_add(am_Constraint *cons) {
    am_Solver *S = cons ? cons->S : NULL;
    am_Symbol sym;
    am_Row row;
    int ret;
    amC(S && cons->marker.id == 0);
    if (cons->marker_id == 0)
        cons->marker_id = ((sym = am_newsymbol(S, 0)), sym.id);
    if (cons->other_id == 0 && cons->strength < AM_REQUIRED)
        cons->other_id = ((sym = am_newsymbol(S, 0)), sym.id);
    row = am_makerow(S, cons);
    if ((ret = am_try_addrow(S, &row, cons)) != AM_OK)
        am_remove_errors(S, cons);
    else {
        am_optimize(S, &S->objective);
        if (S->auto_update) am_updatevars(S);
        S->age += 1;
    }
    assert(S->infeasible_rows.id == 0);
    return ret;
}

static am_Symbol am_get_leaving_row(am_Solver *S, am_Symbol marker) {
    am_Symbol first = am_null(), second = am_null(), third = am_null();
    am_Num r1 = AM_NUM_MAX, r2 = AM_NUM_MAX;
    am_Iterator it = am_itertable(&S->rows);
    while (am_nextentry(&it)) {
        am_Row *row = am_val(am_Row,it);
        am_Num *term = (am_Num*)am_gettable(&row->terms, marker.id);
        if (term == NULL) continue;
        if (am_isexternal(it.key))
            third = it.key;
        else if (*term < 0.f) {
            am_Num r = -row->constant / *term;
            if (r < r1) r1 = r, first = it.key;
        } else {
            am_Num r = row->constant / *term;
            if (r < r2) r2 = r, second = it.key;
        }
    }
    return first.id ? first : second.id ? second : third;
}

AM_API void am_remove(am_Constraint *cons) {
    am_Solver *S;
    am_Symbol marker;
    am_Row tmp;
    if (cons == NULL || cons->marker.id == 0) return;
    S = cons->S, marker = cons->marker;
    am_remove_errors(S, cons);
    if (am_takerow(S, marker, &tmp) != AM_OK) {
        am_Symbol leave = am_get_leaving_row(S, marker);
        assert(leave.id != 0);
        am_takerow(S, leave, &tmp);
        am_solvefor(S, &tmp, marker, leave);
        am_substitute_rows(S, marker, &tmp);
    }
    am_freerow(S, &tmp);
    am_optimize(S, &S->objective);
    S->age += 1;
    if (S->auto_update) am_updatevars(S);
}

AM_API int am_setstrength(am_Constraint *cons, am_Num strength) {
    amC(cons);
    strength = am_nearzero(strength) ? AM_REQUIRED : strength;
    if (cons->strength == strength) return AM_OK;
    if (cons->strength >= AM_REQUIRED || strength >= AM_REQUIRED)
        return am_remove(cons), cons->strength = strength, am_add(cons);
    if (cons->marker.id != 0) {
        am_Solver *S = cons->S;
        am_Num diff = strength - cons->strength;
        am_mergerow(S, &S->objective, cons->marker, diff);
        am_mergerow(S, &S->objective, cons->other,  diff);
        am_optimize(S, &S->objective);
        if (S->auto_update) am_updatevars(S);
        S->age += 1;
    }
    cons->strength = strength;
    return AM_OK;
}

static void am_cached_sugggest(am_Solver *S, am_Suggest *s, am_Num delta) {
    am_Iterator it = am_itertable(&s->dirtyset);
    am_Symbol marker = s->constraint.marker;
    int pure = 1;
    while (am_nextentry(&it)) {
        am_Row *row = (am_Row*)am_gettable(&S->rows, it.key.id);
        am_Num *term;
        assert(row != NULL);
        term = (am_Num*)am_gettable(&row->terms, marker.id);
        assert(term != NULL);
        row->constant += *term * delta;
        if (am_isexternal(it.key))
            am_markdirty(S, it.key);
        else if (am_infeasible(S, it.key, row))
            pure = 0;
    }
    if (!pure) s->age = 0;
}

static void am_delta_edit_constant(am_Solver *S, am_Suggest *s, am_Num delta) {
    am_Iterator it = am_itertable(&S->rows);
    am_Constraint *cons = &s->constraint;
    am_Row *row;
    int pure = 1;
    if ((row = (am_Row*)am_gettable(&S->rows, cons->marker.id)) != NULL)
    { row->constant -= delta, am_infeasible(S, cons->marker, row); return; }
    if ((row = (am_Row*)am_gettable(&S->rows, cons->other.id)) != NULL)
    { row->constant += delta, am_infeasible(S, cons->other, row); return; }
    if (s->age == S->age) { am_cached_sugggest(S, s, delta); return; }
    am_resettable(&s->dirtyset);
    while (am_nextentry(&it)) {
        am_Row *row = am_val(am_Row,it);
        am_Num *term = (am_Num*)am_gettable(&row->terms, cons->marker.id);
        if (term == NULL) continue;
        row->constant += *term*delta;
        am_settable(S, &s->dirtyset, it.key);
        if (am_isexternal(it.key))
            am_markdirty(S, it.key);
        else if (am_infeasible(S, it.key, row))
            pure = 0;
    }
    if (pure) s->age = S->age;
}

static void am_dual_optimize(am_Solver *S) {
    while (S->infeasible_rows.id != 0) {
        am_Symbol enter = am_null(), leave;
        am_Num r, min_ratio = AM_NUM_MAX;
        am_Iterator it;
        am_Row tmp, *row =
            (am_Row*)am_gettable(&S->rows, S->infeasible_rows.id);
        assert(row != NULL);
        leave = S->infeasible_rows;
        S->infeasible_rows = row->infeasible_next;
        row->infeasible_next = am_null();
        if (!am_negative(row->constant)) continue;
        it = am_itertable(&row->terms);
        while (am_nextentry(&it)) {
            am_Num term = *am_val(am_Num,it);
            am_Num *objterm;
            if (am_isdummy(it.key) || term <= 0.f) continue;
            objterm = (am_Num*)am_gettable(&S->objective.terms, it.key.id);
            r = objterm ? *objterm / term : 0.f;
            if (min_ratio > r) min_ratio = r, enter = it.key;
        }
        assert(enter.id != 0);
        am_takerow(S, leave, &tmp);
        am_solvefor(S, &tmp, enter, leave);
        am_substitute_rows(S, enter, &tmp);
        am_putrow(S, enter, &tmp);
    }
}

AM_API void am_suggest(am_Solver *S, am_Id var, am_Num value) {
    am_Suggest **ps, *s;
    am_Num delta;
    if (S == NULL || var == 0) return;
    ps = (am_Suggest**)am_gettable(&S->suggests, var);
    s = ps ? *ps : am_newedit(S, var, AM_MEDIUM);
    assert(s != NULL);
    delta = value - s->edit_value, s->edit_value = value;
    am_delta_edit_constant(S, s, delta);
    am_dual_optimize(S);
    if (S->auto_update) am_updatevars(S);
}

AM_API am_Solver *am_newsolver(am_Allocf *allocf, void *ud) {
    am_Solver *S;
    if (allocf == NULL) allocf = am_default_allocf;
    S = (am_Solver*)allocf(&ud, NULL, sizeof(am_Solver), 0, am_AllocSolver);
    if (S == NULL) return NULL;
    memset(S, 0, sizeof(*S));
    S->ud     = ud;
    S->allocf = allocf;
    am_initrow(&S->objective);
    am_inittable(&S->vars, sizeof(am_Var));
    am_inittable(&S->constraints, sizeof(am_Constraint*));
    am_inittable(&S->suggests, sizeof(am_Suggest*));
    am_inittable(&S->rows, sizeof(am_Row));
    am_initpool(&S->conspool, sizeof(am_Constraint));
    return S;
}

AM_API void am_delsolver(am_Solver *S) {
    am_Iterator it = am_itertable(&S->constraints);
    while (am_nextentry(&it)) {
        am_Constraint *cons = *am_val(am_Constraint*,it);
        am_freerow(S, &cons->expression);
        if (am_isexternal(cons->sym)) am_free(S, cons, am_AllocConstraint);
    }
    it = am_itertable(&S->suggests);
    while (am_nextentry(&it)) {
        am_Suggest *s = *am_val(am_Suggest*,it);
        am_freetable(S, &s->dirtyset);
        am_freetable(S, &s->constraint.expression.terms);
        am_free(S, s, am_AllocSuggest);
    }
    it = am_itertable(&S->rows);
    while (am_nextentry(&it))
        am_freerow(S, am_val(am_Row,it));
    am_freerow(S, &S->objective);
    am_freetable(S, &S->vars);
    am_freetable(S, &S->constraints);
    am_freetable(S, &S->suggests);
    am_freetable(S, &S->rows);
    am_freepool(&S->conspool);
    am_freearena(S, &S->arena);
    am_free(S, S, am_AllocSolver);
}

AM_API void am_resetsolver(am_Solver *S) {
    am_Iterator it;
    if (S == NULL) return;
    am_clearedits(S);
    it = am_itertable(&S->constraints);
    while (am_nextentry(&it)) {
        am_Constraint *cons = *am_val(am_Constraint*,it);
        cons->marker = cons->other = am_null();
    }
    it = am_itertable(&S->rows);
    while (am_nextentry(&it))
        am_freerow(S, am_val(am_Row,it));
    am_resettable(&S->rows);
    am_resetrow(&S->objective);
    am_freearena(S, &S->arena);
    assert(S->infeasible_rows.id == 0);
    S->age = 0;
}

/* dump & load */

#ifndef AM_NAME_LEN
# define AM_NAME_LEN 256
#endif /* AM_NAME_LEN */
#ifndef AM_BUF_LEN
# define AM_BUF_LEN  4096
#endif /* AM_BUF_LEN */

typedef struct am_DumpCtx {
    const am_Solver *S;
    unsigned  *syms; 
    unsigned  *cons;
    am_Table   symmap;
    am_Dumper *dumper;
    char      *p;
    int        ret;
    char       buf[AM_BUF_LEN];
} am_DumpCtx;

static int am_intcmp(const void *lhs, const void *rhs)
{ return *(const int*)lhs - *(const int*)rhs; }

static int am_writechar(am_DumpCtx *ctx, int ch) {
    if ((ctx->p - ctx->buf) >= AM_BUF_LEN) {
        amE(ctx->ret = ctx->dumper->writer(ctx->dumper, ctx->buf, AM_BUF_LEN));
        ctx->p = ctx->buf;
    }
    return (*ctx->p++ = ch & 0xFF), AM_OK;
}

static int am_writeraw(am_DumpCtx *ctx, am_Size n, int width) {
    switch (width) {
    default: return AM_FAILED;
    case 32: amE(am_writechar(ctx, n >> 24));
             amE(am_writechar(ctx, n >> 16)); /* FALLTHROUGH */
    case 16: amE(am_writechar(ctx, n >> 8));
             amE(am_writechar(ctx, n & 0xFF));
    }
    return AM_OK;
}

static int am_writeuint32(am_DumpCtx *ctx, am_Size n) {
    if (n <= 0x7F) amE(am_writechar(ctx, n));
    else if (n <= 0xFF) {
        amE(am_writechar(ctx, 0xCC));
        amE(am_writechar(ctx, n));
    } else if (n <= 0xFFFF) {
        amE(am_writechar(ctx, 0xCD));
        amE(am_writeraw(ctx, n, 16));
    } else {
        amE(am_writechar(ctx, 0xCE));
        amE(am_writeraw(ctx, n, 32));
    }
    return AM_OK;
}

static int am_writefloat(am_DumpCtx *ctx, am_Num n) {
    union { double f64; float f32; unsigned u32; } u;
    if (sizeof(am_Num) == sizeof(float))
        u.f32 = n;
    else
        u.f64 = n, u.f32 = (float)u.f64;
    amE(am_writechar(ctx, 0xCA));
    amE(am_writeraw(ctx, u.u32, 32));
    return AM_OK;
}

static int am_writestring(am_DumpCtx *ctx, const char *name) {
    am_Dumper *d = ctx->dumper;
    size_t namelen = (name ? strlen(name) : 0), buflen;
    amC(namelen < AM_NAME_LEN && namelen <= 0xFF);
    if (namelen < 32)
        amE(am_writechar(ctx, 0xA0 + (int)namelen));
    else {
        amE(am_writechar(ctx, 0xD9));
        amE(am_writechar(ctx, (int)namelen));
    }
    if ((buflen = (ctx->p - ctx->buf)) + namelen > AM_BUF_LEN) {
        ctx->p = ctx->buf;
        if (buflen) amE(ctx->ret = d->writer(d, ctx->buf, buflen));
        if (namelen > AM_BUF_LEN) return ctx->ret = d->writer(d, name, namelen);
    }
    memcpy(ctx->p, name, namelen);
    return ctx->p += namelen, AM_OK;
}

static int am_writecount(am_DumpCtx *ctx, am_Size count) {
    if (count < 16)
        amE(am_writechar(ctx, 0x90 + count));
    else if (count <= 0xFFFF) {
        amE(am_writechar(ctx, 0xDC));
        amE(am_writeraw(ctx, count, 16));
    } else {
        amE(am_writechar(ctx, 0xDD));
        amE(am_writeraw(ctx, count, 32));
    }
    return AM_OK;
}

static unsigned am_mapid(am_DumpCtx *ctx, unsigned key) {
    unsigned *id = (unsigned*)am_gettable(&ctx->symmap, key);
    return assert(id != NULL), *id;
}

static int am_writerow(am_DumpCtx *ctx, const am_Row *row) {
    am_Iterator it = am_itertable(&row->terms);
    amE(am_writecount(ctx, row->terms.count * 2 + 1));
    amE(am_writefloat(ctx, row->constant));
    while (am_nextentry(&it)) {
        amE(am_writeuint32(ctx, am_mapid(ctx, it.key.id) << 2 | it.key.type));
        amE(am_writefloat(ctx, *am_val(am_Num,it)));
    }
    return AM_OK;
}

static int am_writevars(am_DumpCtx *ctx) {
    const am_Solver *S = ctx->S;
    am_Size i;
    amE(am_writecount(ctx, S->vars.count));
    for (i = 0; i < S->vars.count; ++i) {
        am_Var *ve = (am_Var*)am_gettable(&S->vars, ctx->syms[i]);
        const char *vn;
        assert(ve != NULL);
        vn = ctx->dumper->var_name(ctx->dumper, i, ctx->syms[i], ve->pvalue);
        amE(am_writestring(ctx, vn));
    }
    return AM_OK;
}

static int am_writeconstraints(am_DumpCtx *ctx) {
    const am_Solver *S = ctx->S;
    am_Size i;
    amE(am_writecount(ctx, S->constraints.count));
    for (i = 0; i < S->constraints.count; ++i) {
        am_Constraint **ce = (am_Constraint**)am_gettable(
                &S->constraints, ctx->cons[i]);
        unsigned id;
        assert(ce != NULL);
        amE(am_writecount(ctx, 6));
        /* [name, strength, marker, other, relation, row] */
        amE(am_writestring(ctx, ctx->dumper->cons_name ?
                    ctx->dumper->cons_name(ctx->dumper, i, (*ce)) : NULL));
        amE(am_writefloat(ctx, (*ce)->strength));
        if (id = 0, (*ce)->marker.type)
            id = am_mapid(ctx, (*ce)->marker_id) << 2 | (*ce)->marker.type;
        amE(am_writeuint32(ctx, id));
        if (id = 0, (*ce)->other.type)
            id = am_mapid(ctx, (*ce)->other_id) << 2 | (*ce)->other.type;
        amE(am_writeuint32(ctx, id));
        amE(am_writeuint32(ctx, (*ce)->relation));
        amE(am_writerow(ctx, &(*ce)->expression));
    }
    return AM_OK;
}

static int am_writerows(am_DumpCtx *ctx) {
    const am_Solver *S = ctx->S;
    size_t arena = 0;
    am_Iterator it = am_itertable(&S->rows);
    while (am_nextentry(&it))
        arena += am_calcsize(am_val(am_Row,it)->terms.count);
    if (arena > ~(am_Size)0) arena = 0;
    amE(am_writecount(ctx, S->rows.count*2 + 1));
    amE(am_writeuint32(ctx, (am_Size)arena));
    while (am_nextentry(&it)) {
        amE(am_writeuint32(ctx, am_mapid(ctx, it.key.id) << 2 | it.key.type));
        amE(am_writerow(ctx, am_val(am_Row,it)));
    }
    return AM_OK;
}

static int am_collect(am_DumpCtx *ctx) {
    const am_Solver *S = ctx->S;
    am_Symbol sym = {0, 0};
    size_t i, vc = S->vars.count, cc = 0, count = 0;
    am_Iterator it = am_itertable(&S->vars);
    while (am_nextentry(&it)) ctx->syms[count++] = it.key.id;
    it = am_itertable(&S->constraints);
    while (am_nextentry(&it)) {
        am_Constraint *cons = *am_val(am_Constraint*,it);
        if (cons->marker.type) ctx->syms[count++] = cons->marker_id;
        if (cons->other.type) ctx->syms[count++] = cons->other_id;
        ctx->cons[cc++] = it.key.id;
    }
    qsort(ctx->cons, cc, sizeof(unsigned), am_intcmp);
    qsort(ctx->syms, vc, sizeof(unsigned), am_intcmp);
    qsort(ctx->syms + vc, count - vc, sizeof(unsigned), am_intcmp);
    am_inittable(&ctx->symmap, sizeof(unsigned));
    amE(am_growtable(S, &ctx->symmap, count, NULL));
    for (i = 0; i < count; ++i) {
        unsigned *val = (unsigned*)am_settable(S, &ctx->symmap,
                (sym.id = ctx->syms[i], sym));
        assert(val != NULL), *val = (unsigned)i;
    }
    return assert(count == ctx->symmap.count), AM_OK;
}

static int am_dumpall(am_DumpCtx *ctx) {
    const am_Solver *S = ctx->S;
    am_Dumper *d = ctx->dumper;
    amE(am_writecount(ctx, 5));
    /* [total, vars, constraints, rows, objective] */
    amE(am_writeuint32(ctx, ctx->symmap.count));
    amE(am_writevars(ctx));
    amE(am_writeconstraints(ctx));
    amE(am_writerows(ctx));
    amE(am_writerow(ctx, &S->objective));
    if (ctx->p > ctx->buf)
        amE(ctx->ret = d->writer(d, ctx->buf, (ctx->p - ctx->buf)));
    return ctx->ret;
}

AM_API int am_dump(am_Solver *S, am_Dumper *dumper) {
    size_t cons_alloc, sym_alloc;
    am_DumpCtx ctx;
    ctx.ret = AM_FAILED;
    amC(S && dumper && dumper->writer && dumper->var_name);
    am_clearedits(S);
    if (!S->auto_update) am_updatevars(S);
    cons_alloc = sizeof(unsigned) * S->constraints.count;
    sym_alloc = sizeof(unsigned) * (cons_alloc*2 + S->vars.count);
    memset(&ctx, 0, sizeof(ctx));
    ctx.syms = (unsigned*)S->allocf(&S->ud, NULL, sym_alloc, 0, am_AllocDump);
    ctx.cons = (unsigned*)S->allocf(&S->ud, NULL, cons_alloc, 0, am_AllocDump);
    ctx.S = S;
    if (ctx.syms && ctx.cons && (ctx.ret = am_collect(&ctx)) == AM_OK) {
        ctx.dumper = dumper, ctx.p = ctx.buf;
        ctx.ret = am_dumpall(&ctx);
    }
    if (ctx.syms) S->allocf(&S->ud, ctx.syms, 0, sym_alloc, am_AllocDump);
    if (ctx.cons) S->allocf(&S->ud, ctx.cons, 0, cons_alloc, am_AllocDump);
    am_freetable(S, &ctx.symmap);
    return ctx.ret;
}

typedef struct am_LoadCtx {
    am_Solver  *S;
    am_Loader  *loader;
    size_t      n;
    const char *p, *s;
    am_Size     offset;
    char        buf[AM_NAME_LEN];
} am_LoadCtx;

#define am_getchar(ctx) ((ctx)->n-- > 0 ? *(ctx)->p++ & 0xFF : am_fill(ctx))

static int am_fill(am_LoadCtx *ctx) {
    ctx->p = ctx->loader->reader(ctx->loader, &ctx->n);
    amC(ctx->p && ctx->n);
    return ctx->n -= 1, *ctx->p++ & 0xFF;
}

static int am_readraw_slow(am_LoadCtx *ctx, unsigned *pv, int width) {
    int c1 = 0, c2 = 0, c3, c4;
    switch (width) {
    default: return AM_FAILED;
    case 32: amC((c1 = am_getchar(ctx)) != AM_FAILED);
             amC((c2 = am_getchar(ctx)) != AM_FAILED); /* FALLTHROUGH */
    case 16: amC((c3 = am_getchar(ctx)) != AM_FAILED);
             amC((c4 = am_getchar(ctx)) != AM_FAILED);
    }
    return (*pv = c1 << 24 | c2 << 16 | c3 << 8 | c4), AM_OK;
}

static int am_readraw32(am_LoadCtx *ctx, unsigned *pv) {
    if (ctx->n >= 4) {
        unsigned n = *ctx->p++ & 0xFF;
        n <<= 8; n |= *ctx->p++ & 0xFF;
        n <<= 8; n |= *ctx->p++ & 0xFF;
        n <<= 8; n |= *ctx->p++ & 0xFF;
        return *pv = n, ctx->n -= 4, AM_OK;
    }
    return am_readraw_slow(ctx, pv, 32);
}

static int am_readraw16(am_LoadCtx *ctx, unsigned *pv) {
    if (ctx->n >= 2) {
        unsigned n = *ctx->p++ & 0xFF;
        n <<= 8; n |= *ctx->p++ & 0xFF;
        return *pv = n, ctx->n -= 2, AM_OK;
    }
    return am_readraw_slow(ctx, pv, 16);
}

static int am_readuint32(am_LoadCtx *ctx, am_Size *pv) {
    int ty, c;
    switch (ty = am_getchar(ctx)) {
    default: amC(ty <= 0x7F); *pv = ty; break;
    case 0xCC: amC((c = am_getchar(ctx)) != AM_FAILED); *pv = c; break;
    case 0xCD: amE(am_readraw16(ctx, pv)); break;
    case 0xCE: amE(am_readraw32(ctx, pv)); break;
    }
    return AM_OK;
}

static int am_readfloat(am_LoadCtx *ctx, am_Num *pv) {
    union { float f32; unsigned u32[2]; } u;
    amC(am_getchar(ctx) == 0xCA);
    amE(am_readraw32(ctx, &u.u32[0]));
    return *pv = (am_Num)u.f32, AM_OK;
}

static int am_readstring(am_LoadCtx *ctx) {
    char *buf = ctx->buf;
    am_Size size;
    int ty, c;
    switch (ty = am_getchar(ctx)) {
    default:   amC(ty >= 0xA0 && ty <= 0xBF); size = ty - 0xA0;   break;
    case 0xD9: amC((c = am_getchar(ctx)) != AM_FAILED); size = c; break;
    }
    ctx->s = size ? ctx->buf : NULL;
    if (ctx->n >= size)
        return memcpy(ctx->buf, ctx->p, size), ctx->buf[size] = 0,
               ctx->p += size, ctx->n -= size, AM_OK;
    for (;;) {
        memcpy(buf, ctx->p, ctx->n), buf += ctx->n, size -= (am_Size)ctx->n;
        amC((c = am_fill(ctx)) != AM_FAILED);
        *buf++ = c, size -= 1;
        if (size <= ctx->n) {
            memcpy(buf, ctx->p, size), buf[size] = 0;
            return (ctx->n -= size, ctx->p += size), AM_OK;
        }
    }
}

static int am_readcount(am_LoadCtx *ctx, am_Size *pcount) {
    int ty;
    switch (ty = am_getchar(ctx)) {
    default: amC(ty >= 0x90 && ty <= 0x9F); *pcount = ty - 0x90; break;
    case 0xDC: amE(am_readraw16(ctx, pcount)); break;
    case 0xDD: amE(am_readraw32(ctx, pcount)); break; 
    }
    return AM_OK;
}

static int am_readrow(am_LoadCtx *ctx, am_Row *row, void **arena) {
    am_Size i, count, value;
    amE(am_readcount(ctx, &count));
    amC(count >= 1 && (count & 1) == 1);
    amE(am_growtable(ctx->S, &row->terms, count/2, arena));
    amE(am_readfloat(ctx, &row->constant));
    for (i = 1; i < count; i += 2) {
        am_Symbol sym = {0, 0};
        am_Num *term;
        amE(am_readuint32(ctx, &value));
        sym.id = ctx->offset+(value>>2), sym.type = value & 3;
        amC(term = (am_Num*)am_settable(ctx->S, &row->terms, sym));
        amE(am_readfloat(ctx, term));
    }
    return AM_OK;
}

static int am_readvars(am_LoadCtx *ctx) {
    am_Solver *S = ctx->S;
    am_Size i, count;
    am_Symbol sym = {0, AM_EXTERNAL};
    amE(am_readcount(ctx, &count));
    amE(am_growtable(S, &S->vars, count, NULL));
    for (i = 0; i < count; ++i) {
        am_Var *ve;
        am_Num *pvalue;
        amE(am_readstring(ctx));
        pvalue = ctx->loader->load_var(ctx->loader, ctx->s, i, ctx->offset+i);
        amC(pvalue != NULL);
        sym.id = ctx->offset+i;
        amC(ve = (am_Var*)am_settable(S, &S->vars, sym));
        memset(ve, 0, sizeof(*ve));
        ve->pvalue   = pvalue;
        ve->refcount = 1;
    }
    return AM_OK;
}

static int am_readmarker(am_LoadCtx *ctx, am_Symbol *sym, unsigned *id) {
    am_Size value;
    amE(am_readuint32(ctx, &value));
    *id = ctx->offset + (value >> 2);
    sym->type = value & 3;
    if (sym->type) sym->id = *id;
    return AM_OK;
}

static int am_readconstraints(am_LoadCtx *ctx) {
    am_Size i, count, value;
    am_Solver *S = ctx->S;
    amE(am_readcount(ctx, &count));
    amE(am_growtable(S, &S->constraints, count, NULL));
    for (i = 0; i < count; ++i) {
        am_Constraint *cons;
        am_Num strength;
        amE(am_readcount(ctx, &value));
        amC(value == 6); /* [name, strength, marker, other, relation, row] */
        amE(am_readstring(ctx));
        amE(am_readfloat(ctx, &strength));
        amC(cons = am_newconstraint(S, strength));
        if (ctx->loader->load_cons)
            ctx->loader->load_cons(ctx->loader, ctx->s, i, cons);
        amE(am_readmarker(ctx, &cons->marker, &cons->marker_id));
        amE(am_readmarker(ctx, &cons->other, &value));
        cons->other_id = value;
        amE(am_readuint32(ctx, &value));
        amC(value >= AM_LESSEQUAL && value <= AM_GREATEQUAL);
        cons->relation = value;
        amE(am_readrow(ctx, &cons->expression, NULL));
    }
    return AM_OK;
}

static int am_readrows(am_LoadCtx *ctx) {
    am_Solver *S = ctx->S;
    am_Size i, count, value, arena;
    void **arena_buf = NULL, *ptr = NULL;
    amE(am_readcount(ctx, &count));
    amC((count & 1) == 1);
    amE(am_readuint32(ctx, &arena));
    if (arena) {
        am_allocarena(S, &S->arena, arena * (sizeof(am_Key)+sizeof(am_Num)));
        ptr = S->arena.buf, arena_buf = &ptr;
    }
    amE(am_growtable(S, &S->rows, count/2, NULL));
    for (i = 1; i < count; i += 2) {
        am_Symbol sym;
        am_Row *row;
        amE(am_readuint32(ctx, &value));
        sym.id = ctx->offset + (value >> 2), sym.type = value & 3;
        amC(row = (am_Row*)am_settable(S, &S->rows, sym));
        am_initrow(row);
        amE(am_readrow(ctx, row, arena_buf));
    }
    assert(!ptr || (am_Size)((char*)ptr-(char*)S->arena.buf) == S->arena.size);
    return AM_OK;
}

AM_API int am_load(am_Solver *S, am_Loader *loader) {
    am_LoadCtx ctx;
    am_Size count, total;
    amC(S && loader && loader->reader && loader->load_var);
    memset(&ctx, 0, sizeof(ctx));
    ctx.S = S;
    ctx.offset = S->current_id + 1;
    ctx.loader = loader;
    amE(am_readcount(&ctx, &count));
    amC(count == 5); /* [total, vars, constraints, rows, objective] */
    amE(am_readuint32(&ctx, &total));
    amC(ctx.offset + total <= 0x3FFFFFFF);
    am_resetsolver(S);
    amE(am_readvars(&ctx));
    amE(am_readconstraints(&ctx));
    amE(am_readrows(&ctx));
    amE(am_readrow(&ctx, &S->objective, NULL));
    return S->current_id = ctx.offset + total, AM_OK;
}


AM_NS_END

#endif /* AM_IMPLEMENTATION */

/* cc: flags+='-shared -O2 -pedantic -std=c89 -DAM_IMPLEMENTATION -xc'
   unixcc: output='amoeba.so'
   win32cc: output='amoeba.dll' */

