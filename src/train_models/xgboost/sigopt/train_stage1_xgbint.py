#!/usr/bin/env python
# coding: utf-8
import os, time, gc, sys, glob
import pandas as pd
import numpy as np
from sklearn.metrics import log_loss, average_precision_score
from features import *
import yaml
from pathlib import Path
import shutil
import os
import sys
import xgboost
import sigopt.xgboost

os.environ["SIGOPT_API_TOKEN"] = 'EJNLQYETVCMUQVFAZJSWUQUAWJUNFSYVJMQLYTHQNEWGOTOL'
os.environ["SIGOPT_PROJECT"] = "sigopt-xgbint"

very_start = time.time()

def compute_AP(pred, gt):
    return average_precision_score(gt, pred)

def compute_rce_fast(pred, gt):
    cross_entropy = log_loss(gt, pred)
    yt = np.mean(gt)     
    strawman_cross_entropy = -(yt*np.log(yt) + (1 - yt)*np.log(1 - yt))
    return (1.0 - cross_entropy/strawman_cross_entropy)*100.0

def read_data(save_data_path):
    # train = pd.read_parquet(f'{save_data_path}/train/stage1/train_sample2/')
    # valid = pd.read_parquet(f'{save_data_path}/train/stage1/valid_sample/')
    train = pd.read_parquet(f'{save_data_path}/train/stage1/train/')
    valid = pd.read_parquet(f'{save_data_path}/train/stage1/valid/')  

    for col in train.columns:
        if len(col) >= 100:
            new_col = col[-100:]
            train = train.rename(columns={col:new_col})
            valid = valid.rename(columns={col:new_col})

    print(train.shape)
    print(valid.shape)

    return (train, valid)

def save_prediction(oof, valid, save_path):
    for i in range(4):
        valid[f"pred_{label_names[i]}"] = oof[:,i]
    valid[["tweet_id","engaging_user_id",f"pred_{label_names[0]}",f"pred_{label_names[1]}",f"pred_{label_names[2]}",f"pred_{label_names[3]}"]].to_csv(save_path, index=0)
 
def evaluate_results(oof, valid):
    print('#'*25);print('###','Evalution Results');print('#'*25)
    txts = ''
    sumap = 0
    sumrce = 0
    for i in range(1):
        ap = compute_AP(oof[:,i],valid[label_names[i]].values)
        rce = compute_rce_fast(oof[:,i],valid[label_names[i]].values)
        txt = f"{label_names[i]:20} AP:{ap:.5f} RCE:{rce:.5f}"
        print(txt)

        txts += "%.4f" % ap + ' '
        txts += "%.4f" % rce + ' '
        sumap += ap
        sumrce += rce
    print(txts)
    print("AVG AP: ", sumap/4.)
    print("AVG RCE: ", sumrce/4.)


label_names = ['reply_timestamp', 'retweet_timestamp', 'retweet_with_comment_timestamp', 'like_timestamp']
feature_list = []
feature_list.append(stage1_reply_features[:-1])
feature_list.append(stage1_retweet_features[:-1])
feature_list.append(stage1_comment_features[:-1])
feature_list.append(stage1_like_features[:-1])


feature_list2 = []
for item in feature_list:
    feature_list2.append([i if len(i) < 100 else i[-100:] for i in item ])


ROOT_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__),'..', '..','..','..'))

try: 
    with open(os.path.join(ROOT_DIR,'config.yaml'),'r') as file:
        config = yaml.safe_load(file)
except Exception as e:
    print("Errors reading the config file.")

save_data_path = config['files']['save_data_path'] 
model_save_path = config['files']['model_save_path'] 
pred_save_path = config['files']['pred_save_path'] 

xgb_parms = { 
    # 'max_depth':8, 
    # 'learning_rate':0.1, 
    # 'subsample':0.8,
    # 'colsample_bytree':0.8, 
    'eval_metric':'logloss',
    'objective':'binary:logistic',
    'tree_method':'hist',
    "random_state":42
}


if __name__ == "__main__":
    ######## Load data
    train, valid = read_data(save_data_path)
    print("data loaded!")

    ####### Empty array to store prediction values for later evaluation 
    oof = np.zeros((len(valid),len(label_names)))
    
    ######## Train and predict
    for numlabel in range(1):
        start = time.time()
        name = label_names[numlabel]
        print('#'*25);print('###',name);print('#'*25)
        print(f"Feature length for target {name} is {len(feature_list2[numlabel])}")

        print(f"Label counts in training dataset: ")
        print(f"{pd.Series(train[name]).value_counts()}")

        dtrain = xgboost.DMatrix(data=train[feature_list2[numlabel]], label=train[name])
        dvalid = xgboost.DMatrix(data=valid[feature_list2[numlabel]], label=valid[name])

        my_config = dict(
            name="sigopt-xgbint", # Let SigOpt set the tuning parameters, metrics, and budget.
        )

        experiment = sigopt.xgboost.experiment(
            experiment_config=my_config,
            dtrain=dtrain,
            evals=[(dvalid,'valid')],
            params =xgb_parms
        )   

        for run in experiment.get_best_runs():
            sigopt_params = dict(run.assignments) #obtain best SigOpt run's parameter values

        print("HPO took %.1f seconds" % ((time.time()-start)))

        sigopt_run_options = { 'name':'RecSys2021 SigOpt HPO' }
        sigopt_recsys = sigopt.xgboost.run(xgb_parms,
                                    dtrain,
                                    num_boost_round=sigopt_params['num_boost_round'],
                                    early_stopping_rounds=sigopt_params['early_stopping_rounds'],
                                    evals=[(dvalid,'val_set')],
                                    run_options=sigopt_run_options)
        sigopt_model = sigopt_recsys.model
        print(f"View run at https://app.sigopt.com/run/{sigopt_recsys.run.id}")

        print('Predicting...')
        oof[:,numlabel] = sigopt_model.predict(dvalid)

    ######## Merge prediction to data and save
    #save_prediction(oof, valid, f"{pred_save_path}/xgboost_pred_stage1.csv")

    ######## Evaluate the performance
    evaluate_results(oof, valid) 
    
    print('This notebook took %.1f seconds'%(time.time()-very_start))




