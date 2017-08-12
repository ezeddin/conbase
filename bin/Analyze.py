import json
from Stats import *
import pdb
from Params import analyze_params


def json_to_site(f):
    for line in f:
        s = json.loads(line.strip('\n'))    
        samples = dict()
        sample_names = []
        for sample in s['samples'].values():
            snp_pos_list = list(sample['MSP'].keys())
            sample_names.append(sample['name'])
            MSP_dict = dict()
            for pos in snp_pos_list:
                msp_object = MSP()
                msp_object.RR = sample['MSP'][pos]['RR']
                msp_object.RA = sample['MSP'][pos]['RA']
                msp_object.AR = sample['MSP'][pos]['AR']
                msp_object.AA = sample['MSP'][pos]['AA']
                msp_object.stats = sample['MSP'][pos]['stats']
                MSP_dict[int(pos)] = msp_object

            samples[sample['name']] = Sample(sample['name'],sample['AD'], sample['GT'], None, MSP_dict, sample['info'])
        site = Site(s['CHROM'], s['POS'], s['REF'], s['ALTS'], s['TYPE'], samples, sample_names)
        site.BULK_INFO = s['BULK_INFO']
        yield site

def ratio(num1, num2):
    if (num1 + num2) > 0:
        return min(num1, num2)/(num1 + num2)
    else:
        return 0

def define_ms_pair(snp_pos, site):
    pairs = {'AR' : 0, 'AA' : 0}
    for sample in site.samples.values():
        if snp_pos in sample.MSP.keys() and sample.MSP[snp_pos].get_ms_total() >= analyze_params["dp_ms_limit"]:
            msp = sample.MSP[snp_pos]
            RR, RA, AR, AA = msp.RR, msp.RA, msp.AR, msp.AA
            
            min_, min_name = min(([AR, RA], 'AR'), ([RR, AA], 'AA'), key=lambda x: x[0][0]+x[0][1])
            max_, max_name = max(([AR, RA], 'AR'), ([RR, AA], 'AA'), key=lambda x: x[0][0]+x[0][1])
            
            if(ratio(sum(min_),sum(max_)) < analyze_params["ms_group_ratio"] and ratio(max_[0], max_[1]) > analyze_params["win_internal_group_ratio"] ):
                #het gets to vote
                pairs[max_name] += 1
            elif(ratio(sum(min_),sum(max_)) < analyze_params["ms_group_ratio"] and max((RR, 'RR'), (RA, 'RA'), (AR, 'AR'), (AA, 'AR'))[1] in {'AR', 'AA'}):
                #HET-C2 gets to vote
                pairs[max_name] += 1

    max_pair = sorted(list(pairs.items()), reverse=True, key=lambda x: x[1])
    if max_pair[0][1] >= analyze_params["sample_ms_vote_limit"] and ratio(max_pair[0][1], max_pair[1][1]) <= (1-analyze_params["vote_ms_ratio_limit"]):
        return max_pair[0][0]
    else:
        return None

def gt_ratio(site):
    for sample in site.samples.values():
        votes = {'HET-C1':0, 'HET-C2':0, 'HOMO-C1':0,'HOMO-C2':0, 'HOMO-A1':0, 'CONFLICT':0}
        nr_snp_allowed_voting = 0
        ms_pairs = dict()
        for snp_pos in sample.MSP.keys():    
            msp = sample.MSP[snp_pos]
            ms_pair = define_ms_pair(snp_pos, site)
            ms_pairs[snp_pos] = ms_pair
            het, homo_R, homo_A1 = msp.get_msp_ratio(ms_pair)
            
            if msp.get_ms_total() >= analyze_params["dp_ms_limit"]:
                msp.voted = ''
                # if site.POS == 178756156 and sample.name == 'fibroblast_41' and snp_pos == 178756123:
                #     import pdb; pdb.set_trace()
                if ms_pair != None:
                    site.snp_ms_win[snp_pos] = ms_pair              
                    nr_snp_allowed_voting += 1
                    ##CASE: HOMO-C2 or HET-C2
                    if het[2] < analyze_params["msp_internal_ratio"] and homo_R[2] < analyze_params["msp_internal_ratio"]:
                        if homo_R[1] >= analyze_params["msp_ratio"] and het[1] < analyze_params["msp_c2_external_error_ratio"]:
                            hr = max((msp.RR, 'RR'), (msp.RA, 'RA'))
                            if (hr[1] == 'RR' and ms_pair == 'AR') or (hr[1] =='RA' and ms_pair == 'AA'):
                                msp.voted = 'HOMO-C2' #we know for certain this is not a mutation
                            else:
                                msp.voted = 'UNKNOWN'
                        elif homo_R[1] < analyze_params["msp_c2_external_error_ratio"] and het[1] >= analyze_params["msp_ratio"]:
                            ha = max((msp.AA, 'AA'), (msp.AR, 'AR'))
                            if (ha[1] == 'AA' and ms_pair == 'AR') or (ha[1] =='AR' and ms_pair == 'AA'):
                                msp.voted = 'CONFLICT'#this is contradictory
                            else:
                                msp.voted = 'HET-C2'
                        else:
                            msp.voted = 'UNKNOWN'

                    ##CASE: HET or HOMO-C1 or HOMO-A1 if it's only one true msp
                    else:
                        msp_list = [m for m in [het, homo_R, homo_A1] if m[1] >= analyze_params["msp_ratio"] and m[2] >= analyze_params["msp_internal_ratio"]]
                        if len(msp_list) == 1:
                            if msp_list[0][0] == 'HET-C1':
                                if msp_list[0][3] == ms_pair:
                                    msp.voted = 'HET-C1'   #mut-snp pair match!
                                else:                   
                                    msp.voted = 'CONFLICT'              #match is not right
                            else:
                                msp.voted = msp_list[0][0]       #homo-C1 or homo-A1
                        elif len(msp_list) > 1:
                            msp.voted = 'CONFLICT'
                        else:
                            error_list = [m for m in [het, homo_R, homo_A1] if m[1] >= analyze_params["msp_c2_external_error_ratio"] and m[2] >= analyze_params["msp_internal_ratio"]]
                            if len(error_list) > 1:
                                msp.voted = 'CONFLICT'
                            else:
                                msp.voted = 'UNKNOWN'

                    if msp.voted != '' and msp.voted != 'UNKNOWN':
                        votes[msp.voted] += 1

        for k,v in list(votes.items()):
            if k == 'HET-C2' and votes['HOMO-A1'] == 0 and votes['HET-C1'] > 0:
                votes['HET-C1'] += v
                votes[k] = 0
            elif k == 'HET-C2' and votes['HET-C1'] == 0 and votes['HOMO-A1'] > 0 :
                votes['HOMO-A1'] += v
                votes[k] = 0
            elif k == 'HOMO-C2' and votes['HOMO-C1'] > 0:
                votes['HOMO-C1'] += v
                votes[k] = 0
        

        total_votes = sum(list(votes.values()))
        if total_votes >= 1:
            if votes['HOMO-C2'] != 0 and votes['HET-C2'] != 0:
                sample.info = 'CONFLICT'
            else:
                max_vote = sorted(votes.items(), reverse = True, key = lambda t: t[1])
                vote_limit = max_vote[0][1]/total_votes
                if vote_limit >= analyze_params["snp_total_vote"]:
                    if max_vote[0][0] == 'HOMO-C1' or max_vote[0][0] == 'HOMO-C2':
                        alts_dp = sum([v for k, v in sample.AD.items() if k != site.REF])

                        if sum(sample.AD.values()) > 0 and float(alts_dp)/sum(sample.AD.values()) <= analyze_params["homo_error_allowed"]:
                            if float(total_votes)/nr_snp_allowed_voting >= analyze_params["snp_vote_ratio"]:
                                sample.info = max_vote[0][0]
                            else:
                                sample.info = 'UNKNOWN'
                        else:
                            sample.info = 'CONFLICT'
                    else:
                        if float(total_votes)/nr_snp_allowed_voting >= analyze_params["snp_vote_ratio"]:
                            sample.info = max_vote[0][0]
                        else:
                            sample.info = 'UNKNOWN'
                else:
                    #TODO Homo-C1 = HOMO-C2
                    sample.info = 'CONFLICT'
        else:
            support_unmutated = 0
            for snp_pos in sample.MSP.keys():    
                msp = sample.MSP[snp_pos]
                ms_pair = ms_pairs[snp_pos]
                if (ms_pair == 'AA' and msp.RA >= analyze_params["c3_homo_limit"]) or (ms_pair == 'AR' and msp.RR >= analyze_params["c3_homo_limit"]):
                    support_unmutated += 1
            if support_unmutated > 0:
                if sample.AD[site.ALTS['A1']] == 0:
                    sample.info = 'HOMO-C3'
                elif sample.AD[site.ALTS['A1']] >= analyze_params["c3_a1_limit"]:
                    sample.info = 'C3-CONFLICT'
                else:
                    sample.info = 'UNKNOWN'
            elif sample.AD[site.ALTS['A1']] >= analyze_params["c3_a1_limit"]:
                sample.info = 'HET-C3'
            else:
                if sum(sample.AD.values()) > 0:
                    sample.info = 'NOT-INFORMATIVE'
                else:
                    sample.info = 'ZERO-READS'

    
            