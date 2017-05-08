import os
import sys
import subprocess32 as subprocess
sys.path.append('../') #go up one in the modules
import stage_wrapper

#function for auto-making svedb stage entries and returning the stage_id
class delly(stage_wrapper.Stage_Wrapper):
    #path will be where a node should process the data using the in_ext, out_ext
    #stage_id should be pre-registered with db, set to None will require getting
    #a new stage_id from the  db by writing and registering it in the stages table
    def __init__(self,wrapper,dbc,retrieve,upload,params):
        #inheritance of base class stage_wrapper    
        stage_wrapper.Stage_Wrapper.__init__(self,wrapper,dbc,retrieve,upload,params)

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        return 0  
    
    #override this function in each wrapper...
    #this is an older pipeline and not for somatic, will do a new somatic
    def run(self,run_id,inputs):
        #workflow is to run through the stage correctly and then check for error handles
             
        #[1a]get input names and output names setup
        in_names = {'.fa':inputs['.fa'][0],
                    '.bam':inputs['.bam']}
        #will have to figure out output file name handling
        out_exts = self.split_out_exts()
        out_dir = self.strip_name(in_names['.fa']) #default output directory
        if inputs.has_key('out_dir'):
            out_dir = inputs['out_dir'][0]
            stripped_name = self.strip_path(self.strip_in_ext(in_names['.bam'][0],'.bam'))
            out_names = {'.vcf' :out_dir+stripped_name+'_S'+str(self.stage_id)+out_exts[0]}
        else:
            cascade = self.strip_in_ext(in_names['.bam'][0],'.bam')
            out_names = {'.vcf' :cascade+'_S'+str(self.stage_id)+out_exts[0]}  
        #[2a]build command args
        sub_dir = out_dir+'/'+'S'+str(self.stage_id)+'/'
        if not os.path.exists(sub_dir): os.makedirs(sub_dir)
        
        #add load libs parameters for OPEN_MP to do || processing        
        #will have to make some connection changes here
        delly = self.software_path+'/delly-0.7.2/delly_MP_0.7.2' #updated binary
        excl  = self.software_path+'/delly-0.7.2/excludeTemplates/human.hg19.excl.tsv'#need to match reference
        vcfs  = {'del':sub_dir+'del.vcf','dup':sub_dir+'dup.vcf',
                 'inv':sub_dir+'inv.vcf','tra':sub_dir+'tra.vcf',
                 'ins':sub_dir+'ins.vcf'}
        q = str(self.get_params()['q']['value'])
        s = str(self.get_params()['s']['value'])
        del_call = [delly,'-t','DEL','-q',q,'-s',s,
                    '-x',excl,'-o',vcfs['del'],'-g',in_names['.fa']]+in_names['.bam']
        dup_call = [delly,'-t','DUP','-q',q,'-s',s,
                    '-x',excl,'-o',vcfs['dup'],'-g',in_names['.fa']]+in_names['.bam']
        inv_call = [delly,'-t','INV','-q',q,'-s',s,
                    '-x',excl,'-o',vcfs['inv'],'-g',in_names['.fa']]+in_names['.bam']
        tra_call = [delly,'-t','TRA','-q',q,'-s',s,
                    '-x',excl,'-o',vcfs['tra'],'-g',in_names['.fa']]+in_names['.bam']
        ins_call = [delly,'-t','INS','-q',q,'-s',s,
                    '-x',excl,'-o',vcfs['ins'],'-g',in_names['.fa']]+in_names['.bam']
        self.db_start(run_id,in_names['.bam'][0])        
        #[3a]execute the command here----------------------------------------------------
        output,err = '',{}
        try: #should split these up for better robustness...
            output += subprocess.check_output(' '.join(del_call),
                                              stderr=subprocess.STDOUT,shell=True)+'\n'
            output += subprocess.check_output(' '.join(dup_call),
                                              stderr=subprocess.STDOUT,shell=True)+'\n' 
            output += subprocess.check_output(' '.join(inv_call),
                                              stderr=subprocess.STDOUT,shell=True)+'\n' 
            output += subprocess.check_output(' '.join(tra_call),
                                              stderr=subprocess.STDOUT,shell=True)+'\n'
            output += subprocess.check_output(' '.join(ins_call),
                                              stderr=subprocess.STDOUT,shell=True)+'\n'
            #new version has ins_call too, will add
        #catch all errors that arise under normal call behavior
        except subprocess.CalledProcessError as E:
            print('call error: '+E.output)        #what you would see in the term
            err['output'] = E.output
            #the python exception issues (shouldn't have any...
            print('message: '+E.message)          #?? empty
            err['message'] = E.message
            #return codes used for failure....
            print('code: '+str(E.returncode))     #return 1 for a fail in art?
            err['code'] = E.returncode
        except OSError as E:
            print('os error: '+E.strerror)        #what you would see in the term
            err['output'] = E.strerror
            #the python exception issues (shouldn't have any...
            print('message: '+E.message)          #?? empty
            err['message'] = E.message
            #the error num
            print('code: '+str(E.errno))
            err['code'] = E.errno
        print('output:\n'+output)

        #merge/filter all the calls into one .vcf with vcftools
        #bgzip and tabix the files and run vcf-merge on them...
        tabix = self.software_path+'/tabix-0.2.6/tabix'
        bgzip = self.software_path+'/tabix-0.2.6/bgzip'
        PATH = self.software_path+'/tabix-0.2.6:'+ \
               self.software_path+'/vcftools_0.1.12b/bin:'+os.environ['PATH']
        PERL = self.software_path+'/vcftools_0.1.12b/perl'
        if os.environ.has_key('PERL5LIB'):
            PERL += ':'+os.environ['PERL5LIB']
        types = [] #base call types that succeeded
        for k in vcfs:
            if os.path.exists(vcfs[k]): types+=[vcfs[k].split('.vcf')[0]]
        print(types)
        try:
            print('merging seperate variant types into a single .vcf file....')
            for t in types:
                subprocess.check_output(' '.join([bgzip,t+'.vcf']),
                                        stderr=subprocess.STDOUT,shell=True,env={'PATH':PATH})
                subprocess.check_output(' '.join([tabix,'-p','vcf',t+'.vcf.gz']),
                                        stderr=subprocess.STDOUT,shell=True,env={'PATH':PATH})
            #merge with vcf-merge or vcf-concat
            vcfmerge = ['vcf-merge']+[i+'.vcf.gz' for i in types]+['>',out_names['.vcf']]
            subprocess.check_output(' '.join(vcfmerge), stderr=subprocess.STDOUT,
                                    shell=True,env={'PATH':PATH,'PERL5LIB':PERL})
            #now remove the folder...
            #subprocess.check_output('rm -rf %s'%sub_dir, stderr=subprocess.STDOUT,shell=True)                        
        #catch all errors that arise under normal call behavior
        except subprocess.CalledProcessError as E:
            print('call error: '+E.output)        #what you would see in the term
            err['output'] = E.output
            #the python exception issues (shouldn't have any...
            print('message: '+E.message)          #?? empty
            err['message'] = E.message
            #return codes used for failure....
            print('code: '+str(E.returncode))     #return 1 for a fail in art?
            err['code'] = E.returncode
        except OSError as E:
            print('os error: '+E.strerror)        #what you would see in the term
            err['output'] = E.strerror
            #the python exception issues (shouldn't have any...
            print('message: '+E.message)          #?? empty
            err['message'] = E.message
            #the error num
            print('code: '+str(E.errno))
            err['code'] = E.errno
        print('output:\n'+output)
                                                
        #[3b]check results--------------------------------------------------
        if err == {}:
            results = [out_names['.vcf']]
            #for i in results: print i
            if all([os.path.exists(r) for r in results]):
                print("sucessfull........")
                self.db_stop(run_id,self.vcf_to_vca(out_names['.vcf']),'',True)
                return results   #return a list of names
            else:
                print("failure...........")
                self.db_stop(run_id,{'output':output},'',False)
                return False
        else:
            print("failure...........")
            self.db_stop(run_id,{'output':output},err['message'],False)
            return None