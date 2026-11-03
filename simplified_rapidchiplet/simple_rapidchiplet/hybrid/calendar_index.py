"""Exact free-gap index for deterministic resource calendars.

An augmented treap skips subtrees whose largest internal gap is too short.
It changes the data structure, not resource occupancy or schedule policy.
"""
import math
EPS = 1e-18

class _Node:
    __slots__=('start','finish','name','priority','left','right','first','last','gap')
    def __init__(self,start,finish,name,priority):
        self.start,self.finish,self.name,self.priority=start,finish,name,priority
        self.left=self.right=None
        self.first,self.last,self.gap=start,finish,0.

def _refresh(n):
    l,r=n.left,n.right
    n.first=l.first if l else n.start
    n.last=max(n.finish,l.last if l else n.finish,r.last if r else n.finish)
    n.gap=max(0.,l.gap if l else 0.,r.gap if r else 0.,
        n.start-l.last if l else 0.,r.first-n.finish if r else 0.)
    return n

def _insert(root,new):
    if root is None:return new
    if (new.start,new.finish,new.name)<(root.start,root.finish,root.name):
        root.left=_insert(root.left,new)
        if root.left.priority<root.priority:
            top=root.left;root.left=top.right;top.right=_refresh(root);root=top
    else:
        root.right=_insert(root.right,new)
        if root.right.priority<root.priority:
            top=root.right;root.right=top.left;top.left=_refresh(root);root=top
    return _refresh(root)

def _gap(root,cursor,duration):
    if root is None or root.last<=cursor+EPS:return cursor
    if root.first>=cursor+duration-EPS:return cursor
    # Gap subtraction and start+duration may round differently at an exactly
    # fitting boundary. Prune only with an ULP margin; final predicates retain
    # the historical addition-based comparison and event order.
    rounding=8*math.ulp(max(abs(root.first),abs(root.last),abs(cursor),duration,1e-300))
    if root.gap<duration-EPS-rounding:return max(cursor,root.last)
    cursor=_gap(root.left,cursor,duration)
    if root.start>=cursor+duration-EPS:return cursor
    if root.finish>cursor+EPS:cursor=root.finish
    return _gap(root.right,cursor,duration)

class IndexedCalendar:
    __slots__=('root','random_state')
    def __init__(self):self.root=None;self.random_state=1
    def reserve(self,start,finish,name):
        x=self.random_state
        x^=(x<<13)&0xffffffff;x^=x>>17;x^=(x<<5)&0xffffffff
        self.random_state=x&0xffffffff
        self.root=_insert(self.root,_Node(start,finish,name,self.random_state))
    def first_slot(self,ready,duration):
        return ready if duration==0 else _gap(self.root,ready,duration)

def earliest_indexed(calendars,resources,ready,duration):
    if duration==0:return ready
    cursor=ready
    while True:
        postponed=cursor
        for resource in resources:
            cal=calendars.get(resource)
            if cal is not None:postponed=max(postponed,cal.first_slot(cursor,duration))
        if postponed<=cursor:return cursor
        cursor=postponed
