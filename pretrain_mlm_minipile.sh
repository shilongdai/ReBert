#!/bin/bash

 deepspeed train_mlm.py --output_dir="./rebert_minipile" --final_output_dir "./rebert_minipile_best" \
   --evaluation_strategy "steps" --per_device_train_batch_size 190 --per_device_eval_batch_size 190 \
   --gradient_accumulation_steps 1 \
   --learning_rate 0.001 --max_steps 23000 --weight_decay 0.01 --warmup_ratio 0.02 --lr_scheduler_type "linear" \
   --logging_dir "tb_rebert_minipile" --logging_steps 100 \
   --save_steps 100 --save_strategy "steps" --save_total_limit 10 --load_best_model_at_end True \
   --bf16 True --gradient_checkpointing True --deepspeed "./deepspeed/deepspeed_2.json" \
   --dataset_path "data/minipile_mistral" --eval_name "validation" --tokenizer_name "mistralai/Mistral-7B-Instruct-v0.2"
