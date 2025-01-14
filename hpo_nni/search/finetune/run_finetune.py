# -*- encoding:utf-8 -*-
# Copyright (c) Alibaba, Inc. and its affiliates.
import argparse
import copy
import datetime
import json
import logging
import os

import nni
from hpo_nni.core.metric_utils import get_result
from hpo_nni.core.pyodps_utils import create_odps
from hpo_nni.core.pyodps_utils import kill_instance
from hpo_nni.core.pyodps_utils import run_command
from hpo_nni.core.utils import parse_ini
from hpo_nni.core.utils import remove_filepath
from hpo_nni.core.utils import set_value


def get_params():
  parser = argparse.ArgumentParser()
  parser.add_argument(
      '--config',
      type=str,
      help='config path',
      default='./config_finetune.ini.ini')
  parser.add_argument('--exp_dir', type=str, help='exp dir', default='../exp')
  parser.add_argument(
      '--start_time',
      type=str,
      help='finetune start time',
      default='2022-05-30')
  parser.add_argument(
      '--end_time', type=str, help='finetune end time', default='2022-06-17')
  args, _ = parser.parse_known_args()
  return args


if __name__ == '__main__':

  try:
    args = get_params()
    print('args:', args)

    config = parse_ini(args.config)

    metric_dict = config['metric_config']
    print('metric dict:', metric_dict)

    odps_config = config['odps_config']
    print('odps_config:', odps_config)

    oss_config = config['oss_config']

    o = create_odps(
        access_id=oss_config['accessKeyID'],
        access_key=oss_config['accessKeySecret'],
        project=odps_config['project_name'],
        endpoint=odps_config['odps_endpoint'])

    # get parameters form tuner
    tuner_params = nni.get_next_parameter()

    # for tag
    experment_id = str(nni.get_experiment_id())
    trial_id = str(nni.get_trial_id())

    # for early stop,kill mc instance
    set_value('access_id', oss_config['accessKeyID'], trial_id=trial_id)
    set_value('access_key', oss_config['accessKeySecret'], trial_id=trial_id)
    set_value('project', odps_config['project_name'], trial_id=trial_id)
    set_value('endpoint', odps_config['odps_endpoint'], trial_id=trial_id)

    datestart = datetime.datetime.strptime(args.start_time, '%Y-%m-%d')
    dateend = datetime.datetime.strptime(args.end_time, '%Y-%m-%d')

    sum = 0
    cnt = 0
    while (datestart <= dateend):
      print('datestart:', datestart.strftime('%Y%m%d'))
      easyrec_cmd_config = copy.deepcopy(config['easyrec_cmd_config'])

      # update parameter
      pre_edit = eval(easyrec_cmd_config.get('-Dedit_config_json', '{}'))
      pre_edit.update(tuner_params)
      if cnt > 0:
        pre_edit['train_config.fine_tune_checkpoint'] = os.path.join(
            pre_edit['train_config.fine_tune_checkpoint'],
            experment_id + '_' + trial_id)
      edit_json = json.dumps(pre_edit)
      easyrec_cmd_config['-Dedit_config_json'] = edit_json
      print('-Dedit_config_json:', easyrec_cmd_config['-Dedit_config_json'])
      easyrec_cmd_config['-Dtrain_tables'] = easyrec_cmd_config[
          '-Dtrain_tables'].replace('{bizdate}', datestart.strftime('%Y%m%d'))

      next_day = datestart + datetime.timedelta(days=1)
      easyrec_cmd_config['-Deval_tables'] = easyrec_cmd_config[
          '-Deval_tables'].replace('{eval_ymd}', next_day.strftime('%Y%m%d'))

      pre_day = datestart - datetime.timedelta(days=1)
      easyrec_cmd_config['-Dedit_config_json'] = easyrec_cmd_config[
          '-Dedit_config_json'].replace('{predate}', pre_day.strftime('%Y%m%d'))

      easyrec_cmd_config['-Dmodel_dir'] = easyrec_cmd_config[
          '-Dmodel_dir'].replace('{bizdate}', datestart.strftime('%Y%m%d'))
      easyrec_cmd_config['-Dmodel_dir'] = os.path.join(
          easyrec_cmd_config['-Dmodel_dir'], experment_id + '_' + trial_id)

      print('easyrec_cmd_config:', easyrec_cmd_config)

      # trial id for early stop
      run_command(o, easyrec_cmd_config, trial_id)

      filepath = os.path.join(easyrec_cmd_config['-Dmodel_dir'], 'eval_val/')
      dst_filepath = os.path.join(args.exp_dir, experment_id + '_' + trial_id,
                                  datestart.strftime('%Y%m%d'))
      print('filepath:', filepath)
      print('dst_file_path:', dst_filepath)
      best_res, best_event = get_result(
          filepath,
          dst_filepath,
          metric_dict,
          trial_id,
          oss_config=oss_config,
          nni_report=False)
      if best_res:
        nni.report_intermediate_result(best_res)
        sum += best_res
      cnt += 1
      datestart += datetime.timedelta(days=1)

    if cnt > 0:
      nni.report_final_result(sum / cnt)

  except Exception:
    logging.exception('run finetune error')
    exit(1)

  finally:
    # kill mc instance
    kill_instance(trial_job_id=trial_id)
    # remove json
    remove_filepath(trial_id=trial_id)
