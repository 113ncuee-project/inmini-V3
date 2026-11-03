// Exact deterministic list scheduler. No hardware coefficients or PPA shortcuts.
#include <vector>
#include <queue>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>

struct Node { double s,e,first,last,gap; int left=-1,right=-1,name; uint32_t priority; };
struct Calendar {
    std::vector<Node> nodes; int root=-1; uint32_t random=1;
    void refresh(int i) {
        auto &n=nodes[i];
        n.first=n.left<0?n.s:nodes[n.left].first; n.last=n.e; n.gap=0;
        if(n.left>=0) {const auto &l=nodes[n.left];n.last=std::max(n.last,l.last);n.gap=std::max(n.gap,std::max(l.gap,n.s-l.last));}
        if(n.right>=0) {const auto &r=nodes[n.right];n.last=std::max(n.last,r.last);n.gap=std::max(n.gap,std::max(r.gap,r.first-n.e));}
    }
    bool less(int a,int b) const {
        const auto &x=nodes[a];const auto &y=nodes[b];
        if(x.s!=y.s)return x.s<y.s;if(x.e!=y.e)return x.e<y.e;return x.name<y.name;
    }
    int insert(int i,int fresh) {
        if(i<0)return fresh;
        if(less(fresh,i)) {
            nodes[i].left=insert(nodes[i].left,fresh);
            int l=nodes[i].left;
            if(nodes[l].priority<nodes[i].priority){nodes[i].left=nodes[l].right;nodes[l].right=i;refresh(i);i=l;}
        } else {
            nodes[i].right=insert(nodes[i].right,fresh);
            int r=nodes[i].right;
            if(nodes[r].priority<nodes[i].priority){nodes[i].right=nodes[r].left;nodes[r].left=i;refresh(i);i=r;}
        }
        refresh(i);return i;
    }
    void reserve(double s,double e,int name) {
        random^=random<<13;random^=random>>17;random^=random<<5;
        Node n; n.s=n.first=s;n.e=n.last=e;n.gap=0;n.name=name;n.priority=random;
        int i=(int)nodes.size();nodes.push_back(n);root=insert(root,i);
    }
    double gap(int i,double cursor,double d) const {
        if(i<0)return cursor;const auto &n=nodes[i];
        if(n.last<=cursor+1e-18 || n.first>=cursor+d-1e-18)return cursor;
        double scale=std::max(std::max(std::abs(n.first),std::abs(n.last)),std::max(std::abs(cursor),std::max(d,1e-300)));
        double rounding=8*(std::nextafter(scale,std::numeric_limits<double>::infinity())-scale);
        if(n.gap<d-1e-18-rounding)return std::max(cursor,n.last);
        cursor=gap(n.left,cursor,d);
        if(n.s>=cursor+d-1e-18)return cursor;
        if(n.e>cursor+1e-18)cursor=n.e;
        return gap(n.right,cursor,d);
    }
};
struct Ready {int priority,name,id;double released;};
struct Order {bool operator()(const Ready&a,const Ready&b) const {
    if(a.priority!=b.priority)return a.priority>b.priority;
    if(a.released!=b.released)return a.released>b.released;
    return a.name>b.name;
}};
#ifdef _WIN32
#define EXPORT extern "C" __declspec(dllexport)
#else
#define EXPORT extern "C"
#endif
EXPORT int inmin_schedule(int n,int nr,const double*duration,const int*priorities,const int*names,
    const int*doff,const int*deps,const int*roff,const int*resources,double*starts,double*finishes,int*event_order) {
    try {
        std::vector<Calendar> calendars(nr);std::vector<int> pending(n),counts(nr,0);
        std::vector<std::vector<int>> consumers(n);
        for(int i=0;i<n;i++) {
            pending[i]=doff[i+1]-doff[i];
            for(int j=doff[i];j<doff[i+1];j++){if(deps[j]<0||deps[j]>=n||deps[j]==i)return -2;consumers[deps[j]].push_back(i);}
            for(int j=roff[i];j<roff[i+1];j++)counts[resources[j]]++;
        }
        for(int r=0;r<nr;r++)calendars[r].nodes.reserve(counts[r]);
        std::priority_queue<Ready,std::vector<Ready>,Order> ready;
        auto enqueue=[&](int i) {double release=0;for(int j=doff[i];j<doff[i+1];j++)release=std::max(release,finishes[deps[j]]);
            ready.push(Ready{priorities[i],names[i],i,release});};
        for(int i=0;i<n;i++)if(pending[i]==0)enqueue(i);
        int done=0;
        while(!ready.empty()) {
            Ready row=ready.top();ready.pop();int i=row.id;double cursor=row.released,d=duration[i];
            if(d>0)while(true){double postponed=cursor;
                for(int j=roff[i];j<roff[i+1];j++){auto &c=calendars[resources[j]];postponed=std::max(postponed,c.gap(c.root,cursor,d));}
                if(postponed<=cursor)break;cursor=postponed;
            }
            starts[i]=cursor;finishes[i]=cursor+d;event_order[done++]=i;
            if(d>0)for(int j=roff[i];j<roff[i+1];j++)calendars[resources[j]].reserve(cursor,cursor+d,names[i]);
            for(int user:consumers[i])if(--pending[user]==0)enqueue(user);
        }
        return done==n?0:-3;
    } catch(...) {return -4;}
}

EXPORT int inmin_slack(int n,int nr,const double*duration,const int*names,const int*doff,const int*deps,
    const int*roff,const int*resources,const double*starts,const double*finishes,double*slack) {
    try {
        std::vector<std::vector<int>> succ(n),cal(nr);std::vector<int> counts(n,0),order;
        auto edge=[&](int a,int b){succ[a].push_back(b);counts[b]++;};
        double makespan=0;
        for(int i=0;i<n;i++) {
            makespan=std::max(makespan,finishes[i]);
            for(int j=doff[i];j<doff[i+1];j++)edge(deps[j],i);
            if(finishes[i]>starts[i])for(int j=roff[i];j<roff[i+1];j++)cal[resources[j]].push_back(i);
        }
        for(auto &rows:cal) {
            std::sort(rows.begin(),rows.end(),[&](int a,int b){
                if(starts[a]!=starts[b])return starts[a]<starts[b];
                if(finishes[a]!=finishes[b])return finishes[a]<finishes[b];return names[a]<names[b];});
            for(size_t j=1;j<rows.size();j++)edge(rows[j-1],rows[j]);
        }
        std::priority_queue<std::pair<int,int>,std::vector<std::pair<int,int>>,std::greater<std::pair<int,int>>> ready;
        for(int i=0;i<n;i++)if(!counts[i])ready.push({names[i],i});
        while(!ready.empty()){int i=ready.top().second;ready.pop();order.push_back(i);
            for(int child:succ[i])if(--counts[child]==0)ready.push({names[child],child});}
        if((int)order.size()!=n)return -3;
        std::vector<double> latest(n,makespan);
        for(auto p=order.rbegin();p!=order.rend();++p) {
            int i=*p;double finish=makespan;
            if(!succ[i].empty()){finish=latest[succ[i][0]];for(int child:succ[i])finish=std::min(finish,latest[child]);}
            latest[i]=finish-duration[i];slack[i]=std::max(0.,latest[i]-starts[i]);
        }
        return 0;
    } catch(...) {return -4;}
}
