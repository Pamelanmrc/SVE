import os
import sys
import subprocess32 as subprocess
sys.path.append('../') #go up one in the modules
import stage_wrapper

#function for auto-making svedb stage entries and returning the stage_id
class genome_strip(stage_wrapper.Stage_Wrapper):
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
    #~/software/svtoolkit/lib/...
    def run(self,run_id,inputs):
        #workflow is to run through the stage correctly and then check for error handles
             
        #[1a]get input names and output names setup
        in_names = {'.fa':inputs['.fa'][0],
                    '.fa.svmask.fasta':inputs['.fa.svmask.fasta'][0],
                    '.ploidymap.txt'  :inputs['.ploidymap.txt'][0],
                    '.rdmask.bed' :inputs['.rdmask.bed'][0],
                    '.gcmask.fasta':inputs['.gcmask.fasta'][0],
                    '.bam':inputs['.bam']}
        #will have to figure out output file name handling
        out_exts = self.split_out_exts()
        if inputs.has_key('out_dir'):
            out_dir = inputs['out_dir'][0]
            stripped_name = self.strip_path(self.strip_in_ext(in_names['.bam'][0],'.bam'))
            out_names = {'.del.vcf' :out_dir+stripped_name+'_S'+str(self.stage_id)+out_exts[0],
                         '.del.genotype.vcf' :out_dir+stripped_name+'_S'+str(self.stage_id)+out_exts[1],
                         '.cnv.vcf' :out_dir+stripped_name+'_S'+str(self.stage_id)+out_exts[2],}
        else:
            cascade = self.strip_in_ext(in_names['.bam'][0],'.bam')
            out_names = {'.del.vcf' :cascade+'_S'+str(self.stage_id)+out_exts[0],
                         '.del.genotype.vcf' :cascade+'_S'+str(self.stage_id)+out_exts[1],
                         '.cnv.vcf' :cascade+'_S'+str(self.stage_id)+out_exts[2]}  

        self.db_start(run_id,in_names['.bam'][0]) #add entries to DB
        refd = self.strip_name(in_names['.fa']) #this is a bit hackish
        print(refd)
        if inputs.has_key('chroms'): chroms = inputs['chroms']
        #[2a]build command args
        #environment variable passing here
        soft = self.software_path
        SV_DIR = soft+'/svtoolkit'
        SV_TMPDIR = out_dir+'/temp'
        if not os.path.exists(SV_TMPDIR): os.makedirs(SV_TMPDIR)
        PATH = soft+'/jre1.8.0_51/bin:'+ \
               soft+'/svtoolkit/bwa:'+ \
               soft+'/samtools-1.3:'+ \
               soft+'/bcftools-1.3:'+ \
               soft+'/htslib-1.3:'+ \
               os.environ['PATH']
        LD_LIB = soft+'/svtoolkit/bwa:'+''#dynamic libs
        if os.environ.has_key('LD_LIBRARY_PATH'):
            LD_LIB += ':'+os.environ['LD_LIBRARY_PATH']
        print('checking environment variable = PATH:\n%s'%PATH)
        print('checking environment variable = LD_LIBRARY_PATH:\n%s'%LD_LIB)
        print('checking environment variable = SV_DIR:\n%s'%SV_DIR)
        print('checking environment variable = SV_TMPDIR:\n%s'%SV_TMPDIR)

        #PBS cluster specfic tunning
        CLUSTER = False   #dispatched jobs or not
        RAM = 16         #in gigabytes
        CPU = 6          #tasks
        JOBS = 4         #max concurrent jobs
        TIME = '4:00:00' #5 days, fail quickly
#        QUEUE= 'test'

        #reused paths and files...
        sv = self.software_path+'/svtoolkit'
        classpath = sv+'/lib/SVToolkit.jar:'+sv+'/lib/gatk/GenomeAnalysisTK.jar:'+sv+'/lib/gatk/Queue.jar'
        java  = self.software_path+'/jre1.8.0_51/bin/java -Xmx'+str(RAM)+'g'
        qcmd  = 'org.broadinstitute.gatk.queue.QCommandLine'
        qs    = sv+'/qscript/SVQScript.q'
        gatk  = sv+'/lib/gatk/GenomeAnalysisTK.jar'
        conf  = sv+'/conf/genstrip_parameters.txt'
        gmask = in_names['.fa.svmask.fasta']
        print('svmask file: %s'%gmask)
        ploidy = in_names['.ploidymap.txt']
        print('ploidy file: %s'%ploidy)
        rdmask = in_names['.rdmask.bed']
        print('rdmask file: %s'%rdmask)
        cnmask = in_names['.gcmask.fasta']
        print('cnmask file: %s'%cnmask)
        ref  = in_names['.fa']
        
        sub_dir = out_dir+'/'+'S'+str(self.stage_id)+'/'
        if not os.path.exists(sub_dir): os.makedirs(sub_dir)
        
        #[2] bam file list is needed        
        bams = sub_dir+'/bam_files.list'
        bam_names = '\n'.join(in_names['.bam'])
        with open(bams,'w') as f: f.write(bam_names) #try comma, tab and newline

        #[3] gender_map this is for each sample...?
        #for each sample do a samtools view -SH pull out the RG sample name
        gender_map = sub_dir+'/sample_gender.map' #1 is Paternal 2 is Maternal?
        s = ''
        for bam in in_names['.bam']:
            s += bam.split('/')[-1].split('.')[0]+' '+'1\n' #check to see if this will work
        with open(gender_map,'w') as f: #write the file
            f.write(s)
        
        md   = sub_dir+'/md'
        if not os.path.exists(md): os.makedirs(md)
        rd   = sub_dir+'/run'
        if not os.path.exists(rd): os.makedirs(rd)
        logs = sub_dir+'/logs'
        if not os.path.exists(logs): os.makedirs(logs)
        #scheduler specific commands
        if CLUSTER:
            scheduler  = ['-jobNative "-v SV_DIR=%s"'%SV_DIR,
                          '-jobNative "-v SV_TMPDIR=%s"'%SV_TMPDIR,
                          '-jobNative "-v PATH=%s"'%PATH,
                          '-jobNative "-v LD_LIBRARY_PATH=%s"'%LD_LIB,
                          '-jobNative "-v classpath=%s"'%classpath,
                          '-jobNative "-l nodes=1:ppn=%s,walltime=%s,mem=%sg"'%(str(CPU),str(TIME),str(RAM*2))]
            #job specific commands
            job = ['-gatkJobRunner PbsEngine','-jobRunner PbsEngine','--disableJobReport'] #use LSF on ubuntu?
        else:
            scheduler = []
            job = ['--disableJobReport']
            
        # try writing it to a bash script?
        h = '#!/bin/bash\n'
        h += 'export PATH=%s\n'%PATH
        h += 'export LD_LIBRARY_PATH=%s\n'%LD_LIB
        h += 'export SV_DIR=%s\n'%SV_DIR
        h += 'export SV_TMPDIR=%s\n'%SV_TMPDIR
        h += 'which samtools > /dev/null || exit 1\n'
        h += 'which tabix > /dev/null || exit 1\n'
        h += 'echo `samtools`\n'
        h += 'echo `tabix`\n'       
        
        #[0] Preprocess The Bam Data and Generate MetaData
        pp   = sv+'/qscript/SVPreprocess.q'
        preprocess = [java+' -cp %s'%classpath,
                      qcmd,
                      '-S %s '%pp,
                      '-S %s'%qs,
                      '-gatk %s'%gatk]+job+\
                     ['-cp %s'%classpath,
                     '-configFile %s'%conf,
                     '-tempDir %s'%SV_TMPDIR,
                      '-R %s'%ref,
                      '-runDirectory %s'%rd,
                      '-md %s'%md,
                      '-jobLogDir %s'%logs,
                      '-genomeMaskFile %s'%gmask,
                      '-copyNumberMaskFile %s'%cnmask,
                      '-readDepthMaskFile %s'%rdmask,
                      '-ploidyMapFile %s'%ploidy,
                      '-genderMapFile %s'%gender_map,
                      '-useMultiStep',
                      '-reduceInsertSizeDistributions true',
                      '-bamFilesAreDisjoint true',
                      '-computeGCProfiles true',
                      '-computeReadCounts true',
                      '-I %s'%bams]+\
                     scheduler + ['-run'] #take this off for a dry run
        s = ''
        s += h
        for line in preprocess:
            s += line+' \\\n'
            print(line + ' \\')
        s += '|| exit 1\n'
        print('\n')
        #try writing a bash script and executing that
        with open(rd+'/preprocess.sh','w') as f:
            f.write(s)
        command = ['chmod','a+x',rd+'/preprocess.sh','&&','cd %s'%rd,'&& pwd && ./preprocess.sh']
        output, err = '', {}
        try:
            output = subprocess.check_output(' '.join(command), stderr=subprocess.STDOUT, shell=True,
                                             env={'classpath': classpath, 'PATH': PATH, 'SV_DIR': SV_DIR,
                                                  'SV_TMPDIR': SV_TMPDIR, 'LD_LIBRARY_PATH': LD_LIB})
        # catch all errors that arise under normal call behavior
        except subprocess.CalledProcessError as E:
            print('call error: ' + E.output)  # what you would see in the term
            err['output'] = E.output
            # the python exception issues (shouldn't have any...
            print('message: ' + E.message)  # ?? empty
            err['message'] = E.message
            # return codes used for failure....
            print('code: ' + str(E.returncode))  # return 1 for a fail in art?
            err['code'] = E.returncode
        except OSError as E:
            print('os error: ' + E.strerror)  # what you would see in the term
            err['output'] = E.strerror
            # the python exception issues (shouldn't have any...
            print('message: ' + E.message)  # ?? empty
            err['message'] = E.message
            # the error num
            print('code: ' + str(E.errno))
            err['code'] = E.errno
        print('output:\n' + output)

        #[1] Initial Pooled Deletion Discovery
        dd = sv+'/qscript/SVDiscovery.q'
        del_discovery = [java,'-cp %s'%classpath,
                         qcmd,
                         '-S %s'%dd,
                         '-S %s'%qs,
                         '-gatk %s'%gatk]+job+\
                         ['-cp %s'%classpath,
                          '-configFile %s'%conf,
                          '-tempDir %s'%SV_TMPDIR,
                          '-R %s'%ref,
                          '-runDirectory %s'%rd,
                          '-md %s'%md,
                          '-disableGATKTraversal',
                          '-jobLogDir %s'%logs,
                          '-minimumSize %s'%100,
                          '-maximumSize %s'%1000000,
                          '-genomeMaskFile %s'%gmask,
                          '-genderMapFile %s'%gender_map,
                          '-suppressVCFCommandLines',
                          '-P select.validateReadPairs:false',
                          '-I %s'%bams,
                          '-O %s'%out_names['.del.vcf']]+\
                         scheduler+\
                         ['-run']
        print(del_discovery)
        
        s = ''
        s += h
        for line in del_discovery:
            s += line+' \\\n'
            print(line + ' \\')
        s += '|| exit 1\n'
        print('\n')

        #try writing a bash script and executing that
        with open(rd+'/del_discovery.sh','w') as f:
            f.write(s)
        command = ['chmod','a+x',rd+'/del_discovery.sh','&&','cd %s'%rd,'&& pwd && ./del_discovery.sh']
        output, err = '', {}
        try:
            output = subprocess.check_output(' '.join(command), stderr=subprocess.STDOUT, shell=True,
                                             env={'classpath': classpath, 'PATH': PATH, 'SV_DIR': SV_DIR,
                                                  'SV_TMPDIR': SV_TMPDIR, 'LD_LIBRARY_PATH': LD_LIB})
        # catch all errors that arise under normal call behavior
        except subprocess.CalledProcessError as E:
            print('call error: ' + E.output)  # what you would see in the term
            err['output'] = E.output
            # the python exception issues (shouldn't have any...
            print('message: ' + E.message)  # ?? empty
            err['message'] = E.message
            # return codes used for failure....
            print('code: ' + str(E.returncode))  # return 1 for a fail in art?
            err['code'] = E.returncode
        except OSError as E:
            print('os error: ' + E.strerror)  # what you would see in the term
            err['output'] = E.strerror
            # the python exception issues (shouldn't have any...
            print('message: ' + E.message)  # ?? empty
            err['message'] = E.message
            # the error num
            print('code: ' + str(E.errno))
            err['code'] = E.errno
        print('output:\n' + output)
        
        
        #[2] Genotype Individual Deleteions (this needs the GS_DEL_VCF_splitter.py)
        dg = sv+'/qscript/SVGenotyper.q'
        del_genotyping = [java,'-cp %s'%classpath,
                          qcmd,
                          '-S %s'%dg,
                          '-S %s'%qs,
                          '-gatk %s'%gatk]+job+\
                          ['-cp %s'%classpath,
                           '-configFile %s'%conf,
                           '-tempDir %s'%SV_TMPDIR,
                           '-R %s'%ref,
                           '-runDirectory %s'%rd,
                           '-md %s'%md,
                           '-disableGATKTraversal',
                           '-jobLogDir %s'%logs,
                           '-genomeMaskFile %s'%gmask,
                           '-genderMapFile %s'%gender_map,
                           '-I %s'%bams,
                           '-vcf %s'%out_names['.del.vcf'],
                           '-O %s'%out_names['.del.genotype.vcf']]+\
                          scheduler+\
                          ['-run']
        print(del_genotyping)
        
        s = ''
        s += h
        for line in del_genotyping:
            s += line+' \\\n'
            print(line + ' \\')
        s += '|| exit 1\n'
        print('\n')

        #try writing a bash script and executing that
        with open(rd+'/del_genotyping.sh','w') as f:
            f.write(s)
        command = ['chmod','a+x',rd+'/del_genotyping.sh','&&','cd %s'%rd,'&& pwd && ./del_genotyping.sh']
        output, err = '', {}
        try:
            output = subprocess.check_output(' '.join(command), stderr=subprocess.STDOUT, shell=True,
                                             env={'classpath': classpath, 'PATH': PATH, 'SV_DIR': SV_DIR,
                                                  'SV_TMPDIR': SV_TMPDIR, 'LD_LIBRARY_PATH': LD_LIB})
        # catch all errors that arise under normal call behavior
        except subprocess.CalledProcessError as E:
            print('call error: ' + E.output)  # what you would see in the term
            err['output'] = E.output
            # the python exception issues (shouldn't have any...
            print('message: ' + E.message)  # ?? empty
            err['message'] = E.message
            # return codes used for failure....
            print('code: ' + str(E.returncode))  # return 1 for a fail in art?
            err['code'] = E.returncode
        except OSError as E:
            print('os error: ' + E.strerror)  # what you would see in the term
            err['output'] = E.strerror
            # the python exception issues (shouldn't have any...
            print('message: ' + E.message)  # ?? empty
            err['message'] = E.message
            # the error num
            print('code: ' + str(E.errno))
            err['code'] = E.errno
        print('output:\n' + output)
        
        #[3] GenomeSTRiP2.0 CNV algorithm (this needs the gs_spilt_merge.py)
        cnv = sv+'/qscript/discovery/cnv/CNVDiscoveryPipeline.q'
        cnv_discovery = [java,'-cp %s'%classpath,
                         qcmd,
                         '-S %s'%cnv,
                         '-S %s'%qs,
                         '-gatk %s'%gatk]+job+\
                         ['-cp %s'%classpath,
                          '-configFile %s'%conf,
                          '-tempDir %s'%SV_TMPDIR,
                          '-R %s'%ref,
                          '-runDirectory %s'%rd,
                          '-md %s'%md,
                          '-jobLogDir %s'%logs,
                          #'-genomeMaskFile %s'%gmask,
                          '-genderMapFile %s'%gender_map,
                          '-ploidyMapFile %s'%ploidy,
                          '-I %s'%bams,
                          '-tilingWindowSize %s'%5000,
                          '-tilingWindowOverlap %s'%2500,
                          '-maximumReferenceGapLength %s'%25000,
                          '-boundaryPrecision %s'%200,
                          '-minimumRefinedLength %s'%2500]+\
                          scheduler
        if CLUSTER: cnv_discovery += ['-maxConcurrentStageJobs',str(JOBS),'-run']
        else:       cnv_discovery += ['-run']
        print(cnv_discovery)
        
        s = ''
        s += h
        for line in cnv_discovery:
            s += line+' \\\n'
            print(line + ' \\')
        s += '|| exit 1\n'
        print('\n')

        #try writing a bash script and executing that
        with open(rd+'/cnv_discovery.sh','w') as f:
            f.write(s)
        command = ['chmod','a+x',rd+'/cnv_discovery.sh','&&','cd %s'%rd,'&& pwd && ./cnv_discovery.sh']
        output, err = '', {}
        try:
            output = subprocess.check_output(' '.join(command), stderr=subprocess.STDOUT, shell=True,
                                             env={'classpath': classpath, 'PATH': PATH, 'SV_DIR': SV_DIR,
                                                  'SV_TMPDIR': SV_TMPDIR, 'LD_LIBRARY_PATH': LD_LIB})
        # catch all errors that arise under normal call behavior
        except subprocess.CalledProcessError as E:
            print('call error: ' + E.output)  # what you would see in the term
            err['output'] = E.output
            # the python exception issues (shouldn't have any...
            print('message: ' + E.message)  # ?? empty
            err['message'] = E.message
            # return codes used for failure....
            print('code: ' + str(E.returncode))  # return 1 for a fail in art?
            err['code'] = E.returncode
        except OSError as E:
            print('os error: ' + E.strerror)  # what you would see in the term
            err['output'] = E.strerror
            # the python exception issues (shouldn't have any...
            print('message: ' + E.message)  # ?? empty
            err['message'] = E.message
            # the error num
            print('code: ' + str(E.errno))
            err['code'] = E.errno
        print('output:\n' + output)        
        
        # #then some renaming, conversion and clean up
        # move_vcf = ['mv',sub_dir+'/results/gs_cnv.genotypes.vcf.gz'] #this seems to be hard coded
        # convert_vcf = ['python','gs_slpit_merge.py']
        # clean = ['rm','-rf',SV_TMPDIR, sub_dir] #delete temp, stage_id folder after vcfs are copied
        
        final_vcf = rd+'/S14.vcf'
        #[3b]check results--------------------------------------------------
        if err == {}:
            self.db_stop(run_id,{'output':output},'',True)
            results = [final_vcf]
            #for i in results: print i
            if all([os.path.exists(r) for r in results]):
                print("sucessfull........")
                return results   #return a list of names
            else:
                print("failure...........")
                return False
        else:
            self.db_stop(run_id,{'output':output},err['message'],False)
            return None
