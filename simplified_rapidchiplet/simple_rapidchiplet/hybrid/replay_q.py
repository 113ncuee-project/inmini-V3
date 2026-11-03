"""One-step episodic neural Q learning with replay (gamma=0).

Each action is a complete mapping trial, rewarded only by completed physical
PPA. This is contextual RL, not a claimed long-horizon Actor-Critic or SA.
"""
import math
import random
import numpy as np
import torch
from torch import nn

class ReplayQ:
    def __init__(self,size,seed=7,lr=.001):
        torch.set_num_threads(1);torch.manual_seed(seed)
        self.model=nn.Sequential(nn.Linear(size,96),nn.Tanh(),nn.Linear(96,64),nn.Tanh(),nn.Linear(64,1))
        self.optimizer=torch.optim.Adam(self.model.parameters(),lr=lr)
        self.rng=random.Random(seed);self.replay=[];self.updates=0;self.losses=[];self.last_gradient_norm=0.
    def predict(self,features):
        with torch.no_grad():return self.model(torch.as_tensor(np.asarray(features),dtype=torch.float32)).flatten().numpy()
    def observe(self,features,reward,updates=32):
        self.replay.append((np.asarray(features,dtype=np.float32),float(reward)))
        if len(self.replay)>8192:self.replay.pop(0)
        for _ in range(updates):
            batch=self.rng.sample(self.replay,min(64,len(self.replay)))
            x=torch.tensor(np.stack([r[0] for r in batch]),dtype=torch.float32);y=torch.tensor([r[1] for r in batch],dtype=torch.float32)
            prediction=self.model(x).flatten();loss=nn.functional.smooth_l1_loss(prediction,y,beta=5.)
            self.optimizer.zero_grad();loss.backward()
            self.last_gradient_norm=float(nn.utils.clip_grad_norm_(self.model.parameters(),10.))
            self.optimizer.step();self.updates+=1;self.losses.append(float(loss.detach()))
        self.losses=self.losses[-256:]
    def probabilities(self,features,epsilon):
        q=self.predict(features);temperature=max(1.,float(np.std(q))*.25)
        logits=(q-np.max(q))/temperature;p=np.exp(logits);p/=p.sum()
        return (1-epsilon)*p+epsilon/len(p),q
    def save(self,path):
        torch.save(dict(model=self.model.state_dict(),optimizer=self.optimizer.state_dict(),replay=self.replay,
            updates=self.updates,losses=self.losses,rng=self.rng.getstate()),path)
    def load(self,path):
        d=torch.load(path,map_location='cpu',weights_only=False);self.model.load_state_dict(d['model']);self.optimizer.load_state_dict(d['optimizer'])
        self.replay=d['replay'];self.updates=d['updates'];self.losses=d['losses'];self.rng.setstate(d['rng'])
