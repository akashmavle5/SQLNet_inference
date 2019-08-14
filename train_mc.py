from comet_ml import Experiment
experiment = Experiment(api_key="vPCPPZrcrUBitgoQkvzxdsh9k", parse_args=False, project_name='sqlnet', workspace="wronnyhuang")
experiment.set_name('test_mc')

import json
import torch
from sqlnet.utils import *
from sqlnet.model.seq2sql import Seq2SQL
from sqlnet.model.sqlnet import SQLNet
import numpy as np
import datetime

import argparse
import os
from time import time

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--gpu', default='2,3')
    parser.add_argument('--toy', action='store_true',
            help='If set, use small data; used for fast debugging.')
    parser.add_argument('--suffix', type=str, default='',
            help='The suffix at the end of saved model name.')
    parser.add_argument('--ca', action='store_true',
            help='Use conditional attention.')
    parser.add_argument('--dataset', type=int, default=0,
            help='0: original dataset, 1: re-split dataset')
    parser.add_argument('--rl', action='store_true',
            help='Use RL for Seq2SQL(requires pretrained model).')
    parser.add_argument('--baseline', action='store_true', 
            help='If set, then train Seq2SQL model; default is SQLNet model.')
    parser.add_argument('--train_emb', action='store_true',
            help='Train word embedding for SQLNet(requires pretrained model).')
    args = parser.parse_args()
    experiment.log_parameters(vars(args))
    os.environ['CUDA_VISIBLE_DEVICES'] = args.gpu

    N_word=300
    B_word=42
    if args.toy:
        USE_SMALL=True
        GPU=True
        BATCH_SIZE=15
    else:
        USE_SMALL=False
        GPU=True
        BATCH_SIZE=64
    TRAIN_ENTRY=(True, True, True)  # (AGG, SEL, COND)
    TRAIN_AGG, TRAIN_SEL, TRAIN_COND = TRAIN_ENTRY
    learning_rate = 1e-4 if args.rl else 1e-3

    sql_data, table_data, val_sql_data, val_table_data, \
            test_sql_data, test_table_data, \
            TRAIN_DB, DEV_DB, TEST_DB = load_dataset(
                    args.dataset, use_small=USE_SMALL)
    
    dummy_sql_data, dummy_table_data = load_dataset_dummy(0)
    sql_data.append(dummy_sql_data[0])
    table_data.update(dummy_table_data)

    tic = time()
    word_emb = load_word_emb('glove/glove.%dB.%dd.txt'%(B_word,N_word), \
            load_used=args.train_emb, use_small=USE_SMALL)
    print('time to load word emb: ', time() - tic)

    if not args.baseline:
        model = SQLNet(word_emb, N_word=N_word, use_ca=args.ca,
                gpu=GPU, trainable_emb = args.train_emb)
        print 'done with sqlnet constructor'
        assert not args.rl, "SQLNet can\'t do reinforcement learning."
        
    optimizer = torch.optim.Adam(model.parameters(),
            lr=learning_rate, weight_decay = 0)

    if args.train_emb:
        agg_m, sel_m, cond_m, agg_e, sel_e, cond_e = best_model_name(args)
    else:
        agg_m, sel_m, cond_m = best_model_name(args)

    if args.rl or args.train_emb: # Load pretrained model.
        agg_lm, sel_lm, cond_lm = best_model_name(args, for_load=True)
        print "Loading from %s"%agg_lm
        model.agg_pred.load_state_dict(torch.load(agg_lm))
        print "Loading from %s"%sel_lm
        model.sel_pred.load_state_dict(torch.load(sel_lm))
        print "Loading from %s"%cond_lm
        model.cond_pred.load_state_dict(torch.load(cond_lm))

    if not args.rl:
        print 'init'
        init_acc = epoch_acc(model, BATCH_SIZE,
                val_sql_data, val_table_data, TRAIN_ENTRY)
        best_agg_acc = init_acc[1][0]
        best_agg_idx = 0
        best_sel_acc = init_acc[1][1]
        best_sel_idx = 0
        best_cond_acc = init_acc[1][2]
        best_cond_idx = 0
        print 'Init dev acc_qm: %s\n  breakdown on (agg, sel, where): %s'%\
                init_acc
        
        if TRAIN_AGG:
            torch.save(model.agg_pred.state_dict(), agg_m)
            if args.train_emb:
                torch.save(model.agg_embed_layer.state_dict(), agg_e)
        if TRAIN_SEL:
            torch.save(model.sel_pred.state_dict(), sel_m)
            if args.train_emb:
                torch.save(model.sel_embed_layer.state_dict(), sel_e)
        if TRAIN_COND:
            torch.save(model.cond_pred.state_dict(), cond_m)
            if args.train_emb:
                torch.save(model.cond_embed_layer.state_dict(), cond_e)
                
        for i in range(100):
            
            print 'Epoch %d @ %s'%(i+1, datetime.datetime.now())
            
            loss_epoch = epoch_train(model, optimizer, BATCH_SIZE, sql_data, table_data, TRAIN_ENTRY)
            print ' Loss = %s'%loss_epoch
            
            train_acc_qm = epoch_acc(model, BATCH_SIZE, sql_data, table_data, TRAIN_ENTRY)
            print ' Train acc_qm: %s\n   breakdown result: %s'%train_acc_qm
            
            #val_acc = epoch_token_acc(model, BATCH_SIZE, val_sql_data, val_table_data, TRAIN_ENTRY)
            val_acc = epoch_acc(model, BATCH_SIZE, val_sql_data, val_table_data, TRAIN_ENTRY)
            print ' Dev acc_qm: %s\n   breakdown result: %s'%val_acc
            
            # comet logging
            experiment.log_metric('loss', loss_epoch, step=i)
            experiment.log_metric('train_acc_qm', train_acc_qm[0], step=i)
            experiment.log_metric('val_acc', val_acc[0], step=i)
            
            if TRAIN_AGG:
                if val_acc[1][0] > best_agg_acc:
                    best_agg_acc = val_acc[1][0]
                    best_agg_idx = i+1
                    torch.save(model.agg_pred.state_dict(),
                        'saved_model/epoch%d.agg_model%s'%(i+1, args.suffix))
                    torch.save(model.agg_pred.state_dict(), agg_m)
                    if args.train_emb:
                        torch.save(model.agg_embed_layer.state_dict(),
                        'saved_model/epoch%d.agg_embed%s'%(i+1, args.suffix))
                        torch.save(model.agg_embed_layer.state_dict(), agg_e)
            if TRAIN_SEL:
                if val_acc[1][1] > best_sel_acc:
                    best_sel_acc = val_acc[1][1]
                    best_sel_idx = i+1
                    torch.save(model.sel_pred.state_dict(),
                        'saved_model/epoch%d.sel_model%s'%(i+1, args.suffix))
                    torch.save(model.sel_pred.state_dict(), sel_m)
                    if args.train_emb:
                        torch.save(model.sel_embed_layer.state_dict(),
                        'saved_model/epoch%d.sel_embed%s'%(i+1, args.suffix))
                        torch.save(model.sel_embed_layer.state_dict(), sel_e)
            if TRAIN_COND:
                if val_acc[1][2] > best_cond_acc:
                    best_cond_acc = val_acc[1][2]
                    best_cond_idx = i+1
                    torch.save(model.cond_pred.state_dict(),
                        'saved_model/epoch%d.cond_model%s'%(i+1, args.suffix))
                    torch.save(model.cond_pred.state_dict(), cond_m)
                    if args.train_emb:
                        torch.save(model.cond_embed_layer.state_dict(),
                        'saved_model/epoch%d.cond_embed%s'%(i+1, args.suffix))
                        torch.save(model.cond_embed_layer.state_dict(), cond_e)
                        
            print ' Best val acc = %s, on epoch %s individually'%(
                    (best_agg_acc, best_sel_acc, best_cond_acc),
                    (best_agg_idx, best_sel_idx, best_cond_idx))
            
        experiment.log_asset_folder('saved_model')
